# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Core orchestration layer shared by all execution modes.
#
# Provides:
#   OrchestratorConfig      -- immutable session-level settings bundle
#   ConversationHistory     -- rolling window of user/assistant turn pairs
#   SessionContext          -- per-session skill-output cache for cross-turn injection
#   resolve_execution_model -- model alias → installed Ollama model name
#   orchestrate_prompt      -- tool-calling pipeline: messages → skills → synthesized response
#
# Related modules:
#   - main.py                    -- creates config, dispatches modes
#   - modes/api_mode.py         -- run_api_mode
#   - skill_executor.py          -- execute_tool_call (executes individual skill calls)
#   - skills_catalog_builder.py  -- build_tool_definitions (generates JSON Schema tool specs)
#   - ollama_client.py           -- call_llm_chat (/v1/chat/completions with tools support)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import copy
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from agent_core.ollama_client import call_llm_chat
from agent_core.ollama_client import is_explicit_model_name
from agent_core.ollama_client import list_ollama_models
from agent_core.ollama_client import log_to_session
from agent_core.ollama_client import resolve_model_name
from agent_core.prompt_tokens import resolve_tokens
from utils.runtime_logger import SessionLogger
from agent_core.scratchpad import get_key_names as get_scratchpad_key_names
from agent_core.scratchpad import scratch_list as _scratch_list
from agent_core.scratchpad import scratch_save as _scratch_auto_save
from agent_core.skill_executor import build_catalog_gates
from agent_core.skill_executor import execute_tool_call
from agent_core.skill_executor import is_skill_error
from agent_core.skills.Memory.memory_skill import recall_relevant_memories
from agent_core.skills.Memory.memory_skill import store_prompt_memories
from agent_core.skills.SystemInfo.system_info_skill import get_static_system_info_string
from agent_core.skills_catalog_builder import build_tool_definitions
from utils.workspace_utils import get_workspace_root
from utils.workspace_utils import trunc


# ====================================================================================================
# MARK: SKILL GUIDANCE FLAG
# ====================================================================================================
# Controls whether the skill selection guidance block is included in the system prompt.
# min (False) = lean prompt; relies on JSON Schema tool descriptions only (~350 tok baseline).
# max (True)  = full guidance block injected; adds ~925 tok per call for comparison testing.
_SKILL_GUIDANCE_ENABLED: bool = False


def get_skill_guidance_enabled() -> bool:
    return _SKILL_GUIDANCE_ENABLED


def set_skill_guidance_enabled(enabled: bool) -> None:
    global _SKILL_GUIDANCE_ENABLED
    _SKILL_GUIDANCE_ENABLED = enabled


# ====================================================================================================
# MARK: LAST-RUN STATE
# ====================================================================================================
# Holds references to the context_map and messages list from the most recently completed run.
# Populated at the end of orchestrate_prompt() and available to slash commands (e.g. /compact)
# for ad-hoc inspection and compaction between turns.
# _last_run_lock guards reads and writes so a background scheduler task completing its run
# cannot overwrite these globals while a chat-mode /ctx command is reading them.

_last_context_map: list[dict] = []
_last_messages:    list[dict] = []
_last_run_lock:    threading.Lock = threading.Lock()

# Thread-local used by delegate_subrun to access the active logger, config, and depth
# without passing orchestrator internals through every skill call signature.
_delegate_tls:        threading.local = threading.local()
_MAX_DELEGATE_DEPTH:  int             = 2

# Stop event: set by /stoprun to request early termination of the active run.
# The orchestration loop checks this between rounds; the current in-flight LLM call
# completes normally, then the loop exits. Cleared at the start of each new run.
_stop_event: threading.Event = threading.Event()


def request_stop() -> None:
    """Signal the currently active orchestration run to exit after its current round."""
    _stop_event.set()


def is_stop_requested() -> bool:
    """Return True if a /stoprun has been requested and not yet cleared."""
    return _stop_event.is_set()


def clear_stop() -> None:
    """Clear the stop signal. Called automatically at the start of each new run."""
    _stop_event.clear()


def get_last_context_map() -> list[dict]:
    with _last_run_lock:
        return list(_last_context_map)


def get_last_messages() -> list[dict]:
    with _last_run_lock:
        return list(_last_messages)

# Maximum chars placed in each tool message appended to the model's messages thread.
# Results exceeding _TOOL_MSG_AUTO_SCRATCH_MIN are also auto-saved to the scratchpad under a
# deterministic key (_tc_r{round}_{func}) so the model can use scratch_load() to read the full
# content without blowing through the context budget.
_TOOL_MSG_MAX_CHARS:        int   = 1500
_TOOL_MSG_AUTO_SCRATCH_MIN: int   = 600
# Fraction of the context window (chars / num_ctx*4) that must be consumed before any
# automatic compaction fires. Below this threshold the full thread is kept intact.
COMPACT_THRESHOLD:          float = 0.50


@dataclass
class OrchestratorConfig:
    """Session-level configuration bundle shared by all orchestration calls.

    Passed through the orchestration layer so that adding new session-level settings
    requires only a change to this dataclass and the one construction site in main().
    Fields are intentionally mutable so slash commands (/model, /ctx) can update them
    at runtime without rebuilding the object.
    """
    resolved_model:      str
    num_ctx:              int
    max_iterations:       int
    skills_payload:       dict
    skills_summary_path:  Path | None = None   # set to enable auto-reload on catalog change
    catalog_mtime:        float       = 0.0    # last-seen mtime of skills_summary.md


# ====================================================================================================
# MARK: CONVERSATION HISTORY
# ====================================================================================================
class ConversationHistory:
    """Rolling window of user / assistant turn pairs.

    Keeps at most *max_turns* complete rounds (one user + one assistant message per round).
    Older turns are dropped automatically when the cap is exceeded.
    """

    def __init__(self, max_turns: int = 10):
        self._max_turns = max_turns
        self._turns: list[dict] = []

    # ----------------------------------------------------------------------------------------------------

    def add(self, user: str, assistant: str) -> None:
        self._turns.append({"role": "user",      "content": user})
        self._turns.append({"role": "assistant", "content": assistant})
        cap = self._max_turns * 2
        if len(self._turns) > cap:
            self._turns = self._turns[-cap:]

    def clear(self) -> None:
        self._turns = []

    def as_list(self) -> list[dict]:
        """Return the history as a list suitable for passing to orchestrate_prompt."""
        return list(self._turns)

    def __len__(self) -> int:
        return len(self._turns) // 2   # number of complete turns

    def __bool__(self) -> bool:
        return bool(self._turns)


# ====================================================================================================
# MARK: SESSION CONTEXT
# ====================================================================================================
def _truncate_words(text: str, max_words: int) -> str:
    """Truncate *text* to at most *max_words* words, appending ' ...' when cut."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " ..."


class SessionContext:
    """Structured per-session cache of skill outputs for cross-turn context injection.

    After each orchestration turn the raw skill outputs are distilled into a compact,
    token-efficient form and stored here.  On subsequent turns the last N turns' summaries
    are automatically injected into the final synthesis prompt so the LLM can reference
    prior fetched data (web pages, code output, file content) without re-running the skills.

    Optionally persisted to a JSON file (e.g. in progress/) so state survives restarts
    and scheduled tasks can optionally cross-load each other's context.
    """

    MAX_CONTENT_WORDS = 300   # max words stored per web-extract / file-read body
    MAX_INJECT_TURNS  = 2     # how many prior turns to include in each new prompt

    def __init__(self, session_id: str, persist_path: Path | None = None) -> None:
        self._session_id = session_id
        self._path       = persist_path
        self._turns: list[dict] = []
        if persist_path and persist_path.exists():
            try:
                data = json.loads(persist_path.read_text(encoding="utf-8"))
                self._turns = data.get("turns", [])
            except Exception:
                pass

    # --------------------------------------------------------------------------

    def add_turn(
        self,
        user_prompt: str,
        assistant_response: str,
        skill_outputs: list[dict],
    ) -> None:
        """Append a completed turn with its compact skill-output summary."""
        turn_num = len(self._turns) + 1
        compact  = [self._compact_output(o) for o in skill_outputs]
        self._turns.append({
            "turn":               turn_num,
            "user_prompt":        user_prompt,
            "assistant_response": assistant_response,
            "skill_outputs":      compact,
        })
        self._save()

    # --------------------------------------------------------------------------

    def clear(self) -> None:
        self._turns = []
        self._save()

    def turn_count(self) -> int:
        return len(self._turns)

    def get_turns(self) -> list[dict]:
        """Return a snapshot of all stored turns, safe for external inspection."""
        return list(self._turns)

    # --------------------------------------------------------------------------

    def as_inject_block(self, max_turns: int | None = None) -> str:
        """Return a text block for injection into the synthesis prompt.

        Covers the last *max_turns* turns (default: MAX_INJECT_TURNS).  Returns an
        empty string when there are no prior turns to inject.
        """
        n      = max_turns if max_turns is not None else self.MAX_INJECT_TURNS
        recent = self._turns[-n:] if n else list(self._turns)
        if not recent:
            return ""

        parts = []
        for t in recent:
            lines = [f"Turn {t['turn']} | user: {trunc(t['user_prompt'], 100)}"]
            for o in t["skill_outputs"]:
                skill   = o.get("skill", "?")
                summary = o.get("summary", "")
                lines.append(f"  [{skill}] {summary}")
                for r in o.get("results", []):
                    snippet = trunc(r.get("snippet", ""), 80)
                    lines.append(f"    · {r.get('url', '')}  \"{r.get('title', '')}\"  {snippet}")
                if "content" in o:
                    lines.append(f"    {trunc(o['content'], 1500)}")
            parts.append("\n".join(lines))

        return "Prior turn skill context (for follow-up reference):\n\n" + "\n\n".join(parts)

    # --------------------------------------------------------------------------

    def _compact_output(self, output: dict) -> dict:
        """Distil a raw skill output dict to a compact, token-efficient summary."""
        tool_name = output.get("tool", "")
        module   = Path(output.get("module", "")).stem
        function = output.get("function", "?")
        args     = output.get("arguments", {}) or {}
        result   = output.get("result")

        entry: dict = {"skill": tool_name or f"{module}.{function}"}
        for key in ("query", "url", "path", "file_path", "domain", "topic"):
            if key in args:
                entry[key] = trunc(str(args[key]), 200)
                break

        if result is None:
            entry["summary"] = "(no result)"
        elif isinstance(result, list):
            items = []
            for item in result:
                if isinstance(item, dict):
                    title, url, snippet = _extract_result_fields(item)
                    items.append({
                        "url":     url,
                        "title":   title,
                        "snippet": _truncate_words(snippet, 50),
                    })
            entry["results"] = items
            entry["summary"] = f"{len(items)} result(s) returned"
        elif isinstance(result, dict):
            url  = result.get("url", "")
            text = result.get("text") or result.get("content") or result.get("result", "")
            if url:
                entry["url"] = url
            entry["content"] = _truncate_words(str(text), self.MAX_CONTENT_WORDS)
            entry["summary"] = f"text extracted ({self.MAX_CONTENT_WORDS} word limit)"
        elif isinstance(result, str):
            entry["content"] = _truncate_words(result, self.MAX_CONTENT_WORDS)
            entry["summary"] = f"text output ({len(result)} chars)"
        else:
            entry["summary"] = trunc(str(result), 200)

        return entry

    # --------------------------------------------------------------------------

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"session_id": self._session_id, "turns": self._turns}
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log_to_session(f"[session_context] Warning: failed to persist context to {self._path}: {exc}")


# ====================================================================================================
# MARK: MODEL RESOLUTION
# ====================================================================================================
def resolve_execution_model(requested_model: str) -> str:
    """Resolve a short alias or tag to a fully-qualified installed Ollama model name.

    Falls back to the first available model (with a printed warning) rather than
    crashing, so a machine with no "20b" model still starts cleanly.

    If the requested name is already fully-qualified (contains ':' with no whitespace)
    it is returned as-is without querying the host.  This means a model resolved once
    at session startup is forwarded verbatim to subprocesses (e.g. /test against a
    remote host) without re-resolution against that host's model list.
    """
    # Already fully qualified - trust it; no need to hit /api/tags.
    if is_explicit_model_name(requested_model):
        return requested_model.strip()

    available_models = list_ollama_models()
    if not available_models:
        raise RuntimeError("No models are installed in Ollama. Pull models first, then rerun.")

    resolved = resolve_model_name(requested_model, available_models)
    if resolved is None:
        fallback = available_models[0]
        print(
            f"[model] '{requested_model}' not found - falling back to '{fallback}'.\n"
            f"        Available: {', '.join(available_models)}"
        )
        return fallback

    return resolved

# ====================================================================================================
# MARK: ROUTING HELPERS
# ====================================================================================================
def _build_skill_selection_guidance(skills_payload: dict) -> str:
    # Build a skill selection guidance block from the catalog's purpose descriptions.
    # Produces a natural-language menu that lets the LLM reason about which tool
    # best fits the task. Each entry shows the primary function name(s) and a
    # concise description derived from the skill's purpose field.
    lines: list[str] = []
    for skill in skills_payload.get("skills", []):
        purpose = (skill.get("purpose") or "").strip()
        if not purpose:
            continue

        funcs = skill.get("functions", [])

        # Collect unique function names in order of appearance; skip list_ helpers.
        seen_names: set[str]    = set()
        unique_funcs: list[str] = []
        for f in funcs:
            if "(" not in f:
                continue
            name = f.split("(")[0].strip()
            if name and name not in seen_names and not name.startswith("list_"):
                seen_names.add(name)
                unique_funcs.append(name)

        if not unique_funcs:
            continue

        # First sentence of purpose only. Regex requires whitespace after .!? so
        # decimal numbers like 3.14.2 are preserved. Strip any leading list-marker
        # that leaked through from skill.md bullet formatting.
        sentences   = re.split(r"(?<=[.!?])\s+", purpose)
        description = sentences[0].lstrip("- ").strip()
        if len(description) > 160:
            description = description[:157] + "..."

        func_label = " / ".join(f"`{f}`" for f in unique_funcs[:3])
        triggers   = [t for t in (skill.get("triggers") or []) if t]
        when_str   = ", ".join(f'"{t}"' for t in triggers[:5])
        suffix     = f" (use when: {when_str})" if when_str else ""
        lines.append(f"- {func_label}: {description}{suffix}")

    if not lines:
        return ""
    return "Available tools - select based on what the task requires:\n" + "\n".join(lines)


# ====================================================================================================
# MARK: LOG FORMATTING
# ====================================================================================================
def _extract_result_fields(item: dict) -> tuple[str, str, str]:
    # Extract the canonical display fields from a single result-list dict item.
    # Returns (title, url, snippet) with snippet falling back to the 'body' key.
    title   = item.get("title", "")
    url     = item.get("url", "")
    snippet = item.get("snippet") or item.get("body", "")
    return title, url, snippet


# ----------------------------------------------------------------------------------------------------
def _format_tool_outputs(tool_outputs: list[dict]) -> str:
    """Return a compact structural summary of executed tool calls and their results."""
    if not tool_outputs:
        return "(no tool calls executed)"

    lines: list[str] = []
    for output in tool_outputs:
        tool_name = output.get("tool", "")
        module   = Path(output.get("module", "")).stem
        function = output.get("function", "?")
        args     = output.get("arguments", {}) or {}
        result   = output.get("result")

        heading = f"{tool_name} -> {module}.{function}()" if tool_name else f"{module}.{function}()"
        lines.append(heading)
        for k, v in args.items():
            v_str = trunc(repr(v), 120)
            lines.append(f"  {k} = {v_str}")

        if result is None:
            lines.append("  -> None")
        elif isinstance(result, str):
            result_stripped = result.strip()
            preview_lines   = result_stripped.splitlines()[:50]
            total_lines     = result_stripped.count("\n") + 1
            lines.append(f"  -> str  {len(result)} chars / {total_lines} lines")
            for pl in preview_lines:
                lines.append(f"  {trunc(pl, 110)}")
            if total_lines > 50:
                lines.append(f"  ... ({total_lines - 50} more lines)")
        elif isinstance(result, dict):
            keys = list(result.keys())
            lines.append(f"  -> dict  [{', '.join(str(k) for k in keys)}]")
        elif isinstance(result, list):
            lines.append(f"  -> list  len={len(result)}")
            for item in result:
                if isinstance(item, dict):
                    title, url, snippet = _extract_result_fields(item)
                    if title:
                        lines.append(f"  {trunc(title, 80)}")
                    if url:
                        lines.append(f"    {url}")
                    if snippet:
                        lines.append(f"    {trunc(snippet, 110)}")
        else:
            lines.append(f"  -> {type(result).__name__}: {trunc(str(result), 110)}")

        lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def _build_fallback_answer(user_prompt: str, tool_outputs: list[dict]) -> str:
    """Construct a minimal plain-text answer from raw tool outputs when LLM synthesis fails.

    Used when all synthesis attempts return empty content (e.g. Ollama thinking models that
    only generate internal reasoning tokens via /v1/chat/completions).  Formats each tool
    result into a readable block the user can act on, prefixed with a notice about partial output.
    """
    lines: list[str] = [
        f"(Note: the model did not produce a synthesized answer for: \"{trunc(user_prompt, 80)}\")",
        "Raw tool results follow:",
        "",
    ]
    for output in tool_outputs:
        tool_name = output.get("tool", "") or output.get("function", "unknown")
        args      = output.get("arguments", {}) or {}
        result    = output.get("result")

        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        lines.append(f"[{tool_name}({arg_str})]")

        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    title, url, snippet = _extract_result_fields(item)
                    if title:
                        lines.append(f"  - {title}")
                    if url:
                        lines.append(f"    {url}")
                    if snippet:
                        lines.append(f"    {trunc(str(snippet), 200)}")
                else:
                    lines.append(f"  {trunc(str(item), 200)}")
        elif isinstance(result, dict):
            for k, v in result.items():
                lines.append(f"  {k}: {trunc(str(v), 200)}")
        elif isinstance(result, str):
            for ln in result.splitlines()[:20]:
                lines.append(f"  {ln}")
            if result.count("\n") >= 20:
                lines.append("  ...")
        elif result is not None:
            lines.append(f"  {trunc(str(result), 400)}")

        lines.append("")

    return "\n".join(lines).strip()


# ----------------------------------------------------------------------------------------------------

def _estimate_thread_chars(messages: list[dict]) -> int:
    # Quick sum of content lengths - used for context budget logging before each LLM call.
    return sum(len(m.get("content") or "") for m in messages)


# ----------------------------------------------------------------------------------------------------

def compact_context(context_map: list[dict], messages: list[dict], idx: int) -> bool:
    """Replace messages referenced by context_map[idx] with a compact headline.

    For normal entries: replaces messages[msg_idx] content in-place.
    For history-block entries: replaces all messages in the [msg_idx, msg_idx_end] range
    with a single placeholder in messages[msg_idx] and empties the rest.

    Returns True when the entry was compacted, False when skipped (already compacted,
    no msg_idx stored, or idx out of range).
    """
    if idx < 0 or idx >= len(context_map):
        return False
    entry   = context_map[idx]
    msg_idx = entry.get("msg_idx")
    if msg_idx is None or entry.get("compacted"):
        return False
    orig_chars  = entry["chars"]
    auto_key    = entry.get("auto_key")
    label       = entry.get("label") or entry.get("role", "?")
    ref         = f" -> scratchpad: {auto_key}" if auto_key else ""
    round_n     = entry.get("round", 0)
    placeholder = f"[compacted: rnd {round_n} {label} ({orig_chars:,} chars{ref})]"

    # History-block entries span multiple messages (msg_idx through msg_idx_end inclusive).
    # Replace the first with the placeholder and empty the rest so they consume no tokens.
    msg_idx_end = entry.get("msg_idx_end")
    messages[msg_idx]["content"] = placeholder
    if msg_idx_end is not None and msg_idx_end > msg_idx:
        for i in range(msg_idx + 1, msg_idx_end + 1):
            if i < len(messages):
                messages[i]["content"] = ""

    entry["chars"]     = len(placeholder)
    entry["compacted"] = True
    return True


# ----------------------------------------------------------------------------------------------------

def _assess_compact(
    context_map: list[dict],
    messages:    list[dict],
    round_num:   int,
    num_ctx:     int,
) -> tuple[int, str | None]:
    # Fire compaction only when the thread exceeds COMPACT_THRESHOLD of the context budget.
    # Round-0 entries (system prompt, original user prompt, history) are permanently protected.
    # Candidates are sorted so lossless entries (auto_key set) go first, then by size descending,
    # stopping as soon as usage drops back to or below the threshold.
    # Returns (thread_chars_after, log_line) - log_line is None when nothing was compacted.
    thread_chars   = _estimate_thread_chars(messages)
    # Approximation: 4 chars per token. Good enough for a threshold check; no tokeniser needed.
    budget_chars   = num_ctx * 4
    usage_fraction = thread_chars / budget_chars if budget_chars else 0.0

    if usage_fraction <= COMPACT_THRESHOLD:
        return thread_chars, None

    candidates = [
        (cm_idx, entry)
        for cm_idx, entry in enumerate(context_map)
        if 0 < entry.get("round", 0) <= round_num - 2
        and entry.get("msg_idx") is not None
        and not entry.get("compacted")
    ]
    candidates.sort(key=lambda x: (0 if x[1].get("auto_key") else 1, -x[1].get("chars", 0)))

    # Include the history block as a last-resort candidate (round=0 but large and compactable).
    history_candidates = [
        (cm_idx, entry)
        for cm_idx, entry in enumerate(context_map)
        if entry.get("role") == "hist"
        and entry.get("msg_idx") is not None
        and not entry.get("compacted")
    ]
    # History goes at the end of the list - only compacted when nothing else helped.
    all_candidates = candidates + history_candidates
    compacted_count = 0
    for cm_idx, _entry in all_candidates:
        if compact_context(context_map, messages, cm_idx):
            compacted_count += 1
        thread_chars = _estimate_thread_chars(messages)
        if thread_chars / budget_chars <= COMPACT_THRESHOLD:
            break

    log_line = None
    if compacted_count:
        log_line = (
            f"[context] compacted {compacted_count} message(s) "
            f"(usage was {usage_fraction:.1%} > threshold {COMPACT_THRESHOLD:.0%})"
        )
    return thread_chars, log_line


# ----------------------------------------------------------------------------------------------------

def format_context_map(context_map: list[dict], num_ctx: int) -> str:
    # Renders the per-run context map as a diagnostic table for the log file.
    hdr  = f"  {'#':>3}  {'rnd':>3}  {'role':<6}  {'label':<50}  {'chars':>7}  {'~tok':>6}"
    sep  = "  ---  ---  ------  " + "-" * 50 + "  -------  ------"
    lines = [hdr, sep]
    total_chars = 0
    for idx, entry in enumerate(context_map):
        role         = entry.get("role", "?")
        label        = entry.get("label", "")
        chars        = entry.get("chars", 0)
        auto_key     = entry.get("auto_key")
        round_n      = entry.get("round", 0)
        is_compacted = entry.get("compacted", False)
        total_chars += chars
        if auto_key and not is_compacted:
            label = f"{label} -> {auto_key}"
        if is_compacted:
            label = f"* {label}"
        lines.append(
            f"  {idx:>3}  {round_n:>3}  {role:<6}  {trunc(label, 50):<50}  {chars:>7,}  {chars // 4:>6,}"
        )
    total_tokens = total_chars // 4
    remaining    = num_ctx - total_tokens
    lines.append("")
    lines.append(
        f"  total: {total_chars:,} chars | ~{total_tokens:,} tokens used | "
        f"~{remaining:,} tokens remaining (budget: {num_ctx:,})"
    )
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def _build_system_message(
    ambient_system_info: str,
    session_context: "SessionContext | None",
    skills_payload: dict,
) -> str:
    """Assemble the full system prompt from all runtime context sources.

    Combines core behavioural rules, ambient system info, prior-turn context injection,
    skill selection guidance, and active scratchpad hints into a single system message string.
    Called once per orchestration run, before the tool-calling loop begins.
    """
    system_parts = [
        "You are a helpful AI assistant with access to tools. Follow these rules:",
        "- Use tools when they are the appropriate way to answer the user's request - for real-time data, file operations, task management, computations, and web research.",
        "- After using tools, synthesize the results into a clear, direct answer.",
        "- Never claim a tool action succeeded unless the tool output explicitly confirms it.",
        "- Do not add explanatory preamble - respond with direct answers only. Your final response must contain ONLY the answer. Do not include planning notes, self-commentary, or reasoning steps such as 'We should...', 'Let me...', 'Thus we...', 'Let's retrieve...', or 'We can produce...' in your response.",
        "- Complete ALL steps in the user's request. If the user asks for output to be written to a file, that write must happen as a tool call before you give your final answer.",
        "- When a prompt asks about a person, place, event, concept, or historical figure - always call a research or lookup skill to fetch the content first. Never generate biographical, historical, or factual content from memory.",
        "- When a prompt says 'search for', 'search the web for', 'find information about', or 'look up', you MUST call a search or web tool. Never answer these prompts from internal knowledge without first calling the appropriate tool. If the tool returns no results, report that honestly rather than substituting training-data answers.",
        "- When a prompt explicitly says 'delegate' or asks you to 'delegate a sub-task', you MUST call the delegate tool. Do not substitute research_traverse, search_web, or any other tool - the user is requesting a child orchestration run, not a direct search.",
        "- When a prompt says 'research', 'investigate', 'look into', 'find evidence', or 'deep dive into', you MUST call research_traverse. Never answer these prompts from training data. research_traverse handles its own search frontier; call it with the user's question as the query argument.",
        "- When a web search or page-fetch tool returns no results, report that in a single short sentence only (e.g. 'No results were found for [query].'). Do not write out your reasoning about which other tools to try, what the rules say, or why the tool may have failed.",
        '- Whenever you call fetch_page_text to retrieve specific information, always set the query parameter to your specific question (e.g. fetch_page_text(url=..., query="<your specific question here>")). This applies whether the URL came from a search result or was provided directly by the user. The query parameter runs an isolated extraction so only the relevant facts are returned - this avoids overloading the context with raw page text. Only omit query if the user explicitly asks for raw page content.',
        "- The python execution tool is more reliable for calculations than the model's internal math capabilities.",
        "- The scratchpad tool can store intermediate results across steps.",
        "- The current runtime system info (RAM, disk, OS, etc.) is already provided below - do not call get_system_info_dict unless the user explicitly asks to refresh it.",
    ]
    if ambient_system_info:
        system_parts.append(f"\n{ambient_system_info}")

    prior_inject = session_context.as_inject_block() if session_context else ""
    if prior_inject:
        system_parts.append(f"\nPrior session context:\n{prior_inject}")

    if _SKILL_GUIDANCE_ENABLED:
        skill_guidance = _build_skill_selection_guidance(skills_payload)
        if skill_guidance:
            system_parts.append(f"\n{skill_guidance}")

    scratch_keys = get_scratchpad_key_names()
    if scratch_keys:
        system_parts.append(
            f"\nScratchpad keys currently stored: {', '.join(scratch_keys)}\n"
            "Reference them in skill arguments using {scratch:key} or load them with scratch_load()."
        )

    return "\n".join(system_parts)


# ====================================================================================================
# MARK: COT PREAMBLE STRIPPER
# ====================================================================================================
# Matches planning/self-talk language that some models emit inline before writing the answer.
_COT_PLANNING_RE = re.compile(
    r"\b(?:we should|we can|we need|we will|we could|we\'ll|we\'re|we must|"
    r"let me|let\'s|let us|thus we|so we|now we|next we|i need|i should|i will|i\'ll|"
    r"provide an?\b|provide the\b|need to |should |we want|we are going|"
    r"maybe |perhaps )",
    re.IGNORECASE,
)

# First line of a structured answer - bold heading, markdown heading, table, or list item.
_CONTENT_MARKER_RE = re.compile(r"(?:^|\n)(\*\*|#{1,3} |\| |\d+\. |- )")


# ----------------------------------------------------------------------------------------------------
def _strip_cot_preamble(text: str) -> str:
    # Remove inline chain-of-thought planning prose that some models embed at the top of their
    # final response before writing the actual structured answer. Only strips when:
    #   1. There IS a structured content marker (bold, heading, table, list) further down.
    #   2. Everything before that marker contains recognisable planning language.
    # Leaves responses without preamble completely untouched.
    if not text:
        return text

    # Fast exit: response already starts with formatted content.
    stripped_start = text.lstrip("\n")
    if stripped_start[:2] in ("**", "# ", "##", "| ") or (stripped_start and stripped_start[0] in "#|"):
        return text

    marker = _CONTENT_MARKER_RE.search(text)
    if not marker:
        # Paragraph-split fallback: if the response has multiple newline-separated
        # paragraphs and the earlier ones contain planning language while the final
        # paragraph does not, return only the last paragraph (the actual answer).
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        if len(paragraphs) >= 2:
            last_para  = paragraphs[-1]
            prior_text = "\n\n".join(paragraphs[:-1])
            if _COT_PLANNING_RE.search(prior_text) and not _COT_PLANNING_RE.search(last_para):
                return last_para
        return text

    split_pos = marker.start()
    if text[split_pos] == "\n":
        split_pos += 1  # move past the leading newline so the marker itself is kept

    preamble = text[:split_pos]
    if preamble.strip() and _COT_PLANNING_RE.search(preamble):
        return text[split_pos:].lstrip("\n")

    return text


# ====================================================================================================
# MARK: FILE BLOCK WRITER
# ====================================================================================================
_WRITE_FILE_BLOCK_RE = re.compile(
    r"WRITE_FILE:\s*([^\n]+)\n---FILE_START---[ \t]*\n(.*?)\n?---FILE_END---",
    re.DOTALL,
)

# ----------------------------------------------------------------------------------------------------
def _write_file_blocks(response: str) -> list[str]:
    # Parse WRITE_FILE blocks from the agent's final response and write them to disk.
    # Expected format (each field on its own line):
    #
    #   WRITE_FILE: webresearch/01-Mine/2026-03-22/001-slug.md
    #   ---FILE_START---
    #   file content here (multi-line)
    #   ---FILE_END---
    #
    # Relative paths resolve under data/. Strips a leading data/ prefix so either form works.
    # Silently skips any block whose resolved path escapes the data directory.
    # Returns workspace-relative posix paths for every file written successfully.
    workspace_root = get_workspace_root()
    data_dir       = workspace_root / "data"

    written: list[str] = []
    for match in _WRITE_FILE_BLOCK_RE.finditer(response):
        raw_path  = match.group(1).strip()
        content   = match.group(2)

        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("data/"):
            normalized = normalized[5:]

        candidate = Path(normalized)
        target    = (data_dir / normalized).resolve() if not candidate.is_absolute() else candidate.resolve()

        try:
            target.relative_to(data_dir)
        except ValueError:
            log_to_session(f"[file-blocks] Skipping unsafe path: {raw_path!r}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target.relative_to(workspace_root).as_posix())

    return written


# ====================================================================================================
# MARK: ORCHESTRATION PIPELINE
# ====================================================================================================
def orchestrate_prompt(
    user_prompt: str,
    config: OrchestratorConfig,
    logger: SessionLogger,
    conversation_history: list[dict] | None = None,
    session_context: "SessionContext | None" = None,
    quiet: bool = False,
    delegate_depth: int = 0,
) -> tuple[str, int, int, bool, float]:
    """Run the tool-calling pipeline for one prompt.

    Sends the user message to /v1/chat/completions with JSON Schema tool definitions
    derived from the skills catalog. The model selects and calls tools; each result is
    fed back into the message thread until the model produces a plain-text final answer.

    Returns (final_response, prompt_tokens, completion_tokens, run_success, tokens_per_second).
    When quiet=True, verbose stages are written to the log file only.
    """
    def _log(msg: str = "") -> None:
        logger.log_file_only(msg) if quiet else logger.log(msg)

    def _log_section(title: str) -> None:
        logger.log_section_file_only(title) if quiet else logger.log_section(title)

    def _log_file_only(msg: str = "") -> None:
        logger.log_file_only(msg)

    def _log_section_file_only(title: str) -> None:
        logger.log_section_file_only(title)

    from agent_core.skills_catalog_builder import load_skills_payload

    user_prompt = resolve_tokens(user_prompt)

    # -- Auto-reload catalog if skills_summary.md has been updated since last load --
    if config.skills_summary_path and config.skills_summary_path.exists():
        current_mtime = config.skills_summary_path.stat().st_mtime
        if current_mtime != config.catalog_mtime:
            config.skills_payload  = load_skills_payload(config.skills_summary_path)
            config.catalog_mtime   = current_mtime
            logger.log_file_only("[catalog] skills catalog reloaded (file changed on disk)")

    _log_section("ORCHESTRATION RUN")
    _log(f"Model:          {config.resolved_model}")
    _log(f"Context window: {config.num_ctx:,} tokens")
    _log(f"Max rounds:     {config.max_iterations}")
    _log(f"Prompt:         {user_prompt[:300]}{' ...' if len(user_prompt) > 300 else ''}")

    # -- Memory --
    _log_file_only("[progress] Storing prompt memories...")
    # Persist any facts in the prompt before tool calls run, so the turn is captured even on failure.
    # Skip for slash commands and very short prompts - they cannot contain storable facts.
    if user_prompt.startswith("/") or len(user_prompt.split()) < 4:
        memory_store_result = "Memory storage skipped."
    else:
        memory_store_result = store_prompt_memories(user_prompt=user_prompt)
    _log_file_only("[progress] Recalling relevant memories...")
    # Pull the most relevant prior memories to inject as context in the system prompt.
    recalled_memories   = recall_relevant_memories(user_prompt=user_prompt, limit=5, min_score=0.2)

    _log_section("MEMORY")
    _log(memory_store_result)
    _log(recalled_memories)

    ambient_system_info = get_static_system_info_string()
    _log_section("AMBIENT SYSTEM INFO")
    _log(ambient_system_info)

    # -- Build tool definitions from the skills catalog --
    # Convert the catalog into JSON Schema objects sent to the model on every tool-calling round.
    tool_defs = build_tool_definitions(config.skills_payload)
    _log_file_only(f"[progress] Tool definitions built: {len(tool_defs)} tools available.")

    # -- Build system message --
    system_message = _build_system_message(ambient_system_info, session_context, config.skills_payload)

    # -- Build initial messages list --
    messages: list[dict] = [{"role": "system", "content": system_message}]
    _context_map: list[dict] = [
        {"round": 0, "role": "sys", "label": "system prompt", "chars": len(system_message), "auto_key": None, "msg_idx": 0},
    ]
    if conversation_history:
        _hist_start = len(messages)
        _hist_chars = sum(len(m.get("content") or "") for m in conversation_history)
        # Store msg_idx (first history message) and msg_idx_end (last) so the block can
        # be compacted as a unit when context pressure is high.
        _context_map.append({"round": 0, "role": "hist", "label": f"history ({len(conversation_history)} msgs)", "chars": _hist_chars, "auto_key": None, "msg_idx": _hist_start, "msg_idx_end": _hist_start + len(conversation_history) - 1})
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_prompt})
    _context_map.append({"round": 0, "role": "user", "label": trunc(user_prompt, 50), "chars": len(user_prompt), "auto_key": None, "msg_idx": len(messages) - 1})

    # -- Tool calling loop --
    # Build once for the entire run - avoids re-scanning the catalog on every tool invocation.
    # Store delegate runtime context in thread-local so delegate_subrun() can access the
    # active logger, config, and depth without passing orchestrator internals through skill args.
    _delegate_tls.logger         = logger
    _delegate_tls.delegate_depth = delegate_depth
    _delegate_tls.config         = config
    catalog_gates      = build_catalog_gates(config.skills_payload)
    tool_outputs:      list[dict] = []
    prompt_tokens:     int        = 0
    completion_tokens: int        = 0
    final_tps:         float      = 0.0
    run_success:       bool       = False
    final_response:    str        = ""

    # Clear any leftover stop signal from a previous /stoprun before entering the loop.
    _stop_event.clear()

    for round_num in range(1, config.max_iterations + 1):
        # Check for /stoprun signal before starting a new round.
        if _stop_event.is_set():
            _stop_event.clear()
            _log("[/stoprun] Stop requested - halting before round {round_num}.")
            final_response = "[Run stopped by /stoprun. The previous response may be incomplete.]"
            break

        _log_section(f"TOOL ROUND {round_num}")
        _log_file_only(f"[progress] Round {round_num}: calling model...")

        # -- Compact context if thread exceeds the budget threshold --
        _thread_chars, _compact_log = _assess_compact(_context_map, messages, round_num, config.num_ctx)
        if _compact_log:
            _log_file_only(_compact_log)

        # -- Context budget snapshot before call --
        _log_file_only(
            f"[context] thread: {_thread_chars:,} chars (~{_thread_chars // 4:,} tok est.) | "
            f"window: {config.num_ctx:,} | remaining est.: ~{config.num_ctx - _thread_chars // 4:,}"
        )

        # Send the growing messages thread; the model either answers directly or requests more tool calls.
        try:
            result = call_llm_chat(
                model_name=config.resolved_model,
                messages=messages,
                tools=tool_defs if tool_defs else None,
                num_ctx=config.num_ctx,
            )
        except Exception as error:
            error_str = str(error)
            # Ollama returns HTTP 500 "error parsing tool call" when the model generates
            # a truncated or malformed JSON tool-call argument (common when the model
            # tries to embed a large string literal inline rather than building it via
            # code_execute or scratchpad). Instead of aborting the run, inject a
            # corrective user message so the model can retry with a different approach.
            if "error parsing tool call" in error_str:
                _log(f"[error] Tool call JSON parse error in round {round_num} - injecting correction message.")
                correction = (
                    "Your previous tool call could not be executed because the argument "
                    "JSON was truncated or malformed. Do not embed large multi-line strings "
                    "directly in a tool call argument. Instead: (1) build the content using "
                    "code_execute and print() it, (2) save the output to the scratchpad with "
                    "scratch_save, then (3) pass the scratchpad reference to write_file."
                )
                messages.append({"role": "user", "content": correction})
                _context_map.append({
                    "round":    round_num,
                    "role":     "user",
                    "label":    "[tool-call correction injected]",
                    "chars":    len(correction),
                    "auto_key": None,
                    "msg_idx":  len(messages) - 1,
                })
                continue
            _log(f"[error] LLM call failed in round {round_num}: {error}")
            final_response = f"(LLM call failed: {error})"
            break

        prompt_tokens     += result.prompt_tokens
        completion_tokens += result.completion_tokens
        final_tps          = result.tokens_per_second

        _log(f"Round {round_num} TPS: {final_tps:.1f} tok/s  ({result.completion_tokens} completion | {result.prompt_tokens:,} prompt tokens)")
        _log_file_only(f"[context] actual prompt tokens used: {result.prompt_tokens:,} | remaining: ~{config.num_ctx - result.prompt_tokens:,}")

        _thinking = (result.message.get("thinking") or result.message.get("reasoning") or "").strip()
        if _thinking:
            _log_file_only(f"[thinking]\n{_thinking}\n[/thinking]")

        if not result.tool_calls:
            # Model answered directly - this is the final response.
            final_response = _strip_cot_preamble(result.response)
            run_success    = bool(final_response)
            _log(final_response)
            _log_file_only(f"[progress] Round {round_num}: model gave final answer.")
            messages.append({"role": "assistant", "content": final_response})
            _context_map.append({"round": round_num, "role": "asst", "label": "final answer", "chars": len(final_response), "auto_key": None, "msg_idx": len(messages) - 1})
            break

        # -- Execute each requested tool call --
        _log(f"Round {round_num}: model requested {len(result.tool_calls)} tool call(s).")
        _log_file_only("[progress] Executing tool calls...")

        messages.append({
            "role":       "assistant",
            "content":    result.response or "",
            "tool_calls": result.tool_calls,
        })
        _context_map.append({"round": round_num, "role": "asst", "label": f"(tool calls x{len(result.tool_calls)})", "chars": len(result.response or ""), "auto_key": None, "msg_idx": len(messages) - 1})

        round_outputs: list[dict] = []
        for tc in result.tool_calls:
            tc_id     = tc.get("id", "")
            tc_func   = tc.get("function", {})
            func_name = tc_func.get("name", "")
            raw_args  = tc_func.get("arguments", "{}")

            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                arguments = {}

            arg_preview = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
            _log(f"  -> {func_name}({arg_preview})")

            try:
                output         = execute_tool_call(func_name, arguments, config.skills_payload, user_prompt, catalog_gates)
                result_content = output["result"]
                if not isinstance(result_content, str):
                    result_content = json.dumps(result_content, default=str)
                if output.get("is_error"):
                    result_content = f"[SKILL_ERROR] {result_content}"
            except Exception as exc:
                result_content = f"[SKILL_ERROR] Error executing {func_name}: {exc}"
                output = {"function": func_name, "module": "", "arguments": arguments, "result": result_content, "is_error": True}

            # Auto-save large results to scratchpad; cap message to protect context budget.
            # Scratchpad reader calls (scratch_load, scratch_peek, etc.) are exempt - the data
            # is already in the scratchpad and re-saving it creates a chain of duplicate keys
            # that the model will try to load indefinitely without ever reading the content.
            _is_scratch_reader = func_name.lower().startswith("scratch_")
            auto_scratch_key = None
            if (not output.get("is_error")
                    and not _is_scratch_reader
                    and isinstance(result_content, str)
                    and len(result_content) >= _TOOL_MSG_AUTO_SCRATCH_MIN):
                safe_name        = func_name.lower()[:24]
                auto_scratch_key = f"_tc_r{round_num}_{safe_name}"
                _scratch_auto_save(auto_scratch_key, result_content)
                if len(result_content) > _TOOL_MSG_MAX_CHARS:
                    result_content = (
                        result_content[:_TOOL_MSG_MAX_CHARS]
                        + f"\n... [truncated - full content auto-saved to scratchpad key: {auto_scratch_key}]"
                    )

            _log(f"     {trunc(str(result_content), 120)}")
            round_outputs.append(output)
            tool_outputs.append(output)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc_id,
                "name":         func_name,
                "content":      result_content,
            })
            _context_map.append({"round": round_num, "role": "tool", "label": func_name, "chars": len(result_content), "auto_key": auto_scratch_key, "msg_idx": len(messages) - 1})

        _log_section_file_only(f"TOOL ROUND {round_num} - EXECUTION FLOW")
        _log_file_only(_format_tool_outputs(round_outputs))

    else:
        # Exhausted all rounds without a plain-text answer - request a final synthesis.
        _log("[warn] Max tool rounds exhausted - requesting final synthesis.")
        try:
            # Append an explicit user directive so the model is forced to emit visible content
            # rather than only generating internal thinking tokens (Ollama 0.18+ thinking models).
            synthesis_messages = messages + [{
                "role":    "user",
                "content": "Based on the tool results above, please answer my original question now.",
            }]
            # Call without tools so the model synthesises a final answer from accumulated results.
            result             = call_llm_chat(
                model_name=config.resolved_model,
                messages=synthesis_messages,
                tools=None,
                num_ctx=config.num_ctx,
            )
            final_response     = _strip_cot_preamble(result.response)
            prompt_tokens     += result.prompt_tokens
            completion_tokens += result.completion_tokens
            final_tps          = result.tokens_per_second
            _log_section("FINAL RESPONSE")
            _thinking = (result.message.get("thinking") or result.message.get("reasoning") or "").strip()
            if _thinking:
                _log_file_only(f"[thinking]\n{_thinking}\n[/thinking]")
            _log(final_response)

            # Last-resort fallback: if the model produced no content (e.g. Ollama thinking
            # models that emit only internal reasoning tokens via /v1/chat/completions),
            # build a minimal plain-text answer directly from the collected tool outputs so
            # the user always sees something.
            if not final_response and tool_outputs:
                _log_file_only("[warn] Synthesis returned empty - falling back to tool-output summary.")
                final_response = _build_fallback_answer(user_prompt, tool_outputs)
                _log(final_response)

            run_success = bool(final_response)
        except Exception as error:
            final_response = f"(synthesis failed: {error})"

    # Extract and write any WRITE_FILE blocks embedded in the model's text response.
    _file_blocks_written = _write_file_blocks(final_response) if final_response else []
    if _file_blocks_written:
        _log_file_only(f"[file-blocks] Wrote {len(_file_blocks_written)} file(s): {', '.join(_file_blocks_written)}")

    _log_section_file_only("TOOL CALL SUMMARY")
    _log_file_only(_format_tool_outputs(tool_outputs))
    _log_section_file_only("CONTEXT MAP")
    _log_file_only(format_context_map(_context_map, config.num_ctx))
    _log_section_file_only("SCRATCHPAD STATE")
    _log_file_only(_scratch_list())
    _log(f"Total: {prompt_tokens:,} prompt tokens | {completion_tokens:,} completion tokens")

    # Store last-run state for ad-hoc inspection via /compact and other slash commands.
    global _last_context_map, _last_messages
    with _last_run_lock:
        _last_context_map = _context_map
        _last_messages    = messages

    # Archive this turn's skill outputs so later turns can reference prior results without re-running.
    if session_context is not None and run_success and tool_outputs:
        session_context.add_turn(
            user_prompt=user_prompt,
            assistant_response=final_response,
            skill_outputs=tool_outputs,
        )

    return final_response, prompt_tokens, completion_tokens, run_success, final_tps


# ====================================================================================================
# MARK: DELEGATE SUBRUN
# ====================================================================================================
# Core implementation of the Delegate orchestration primitive.
#
# Creates an isolated child orchestration context for a focused sub-task, runs the normal
# tool-calling pipeline inside it, and returns a compact result dict to the caller.
#
# Accessed by the Delegate skill wrapper (code/skills/Delegate/delegate_skill.py) and also
# callable directly from orchestration code that needs to spawn a sub-run programmatically.
#
# Guard rails enforced here:
#   - Maximum delegation depth: _MAX_DELEGATE_DEPTH
#   - Child loses access to the Delegate tool by default (allow_recursive_delegate=False)
#   - Child does not inherit parent conversation history or session context
#   - Child iteration budget capped at 8 rounds

# ----------------------------------------------------------------------------------------------------
def delegate_subrun(
    prompt: str,
    instructions: str = "",
    max_iterations: int = 3,
    allow_recursive_delegate: bool = False,
) -> dict:
    """Run a child orchestration context for one isolated sub-task.

    Reads the active logger, config, and depth from thread-local state set by
    orchestrate_prompt() at the start of each run. Returns a compact result dict
    suitable for direct use in the parent model's synthesis step.
    """
    prompt       = str(prompt or "").strip()
    instructions = str(instructions or "").strip()

    if not prompt:
        return {
            "status":          "error",
            "answer":          "delegate() requires a non-empty prompt.",
            "delegate_prompt": "",
            "depth":           0,
            "max_iterations":  max_iterations,
        }

    _logger = getattr(_delegate_tls, "logger", None)
    _depth  = int(getattr(_delegate_tls, "delegate_depth", 0))
    _config = getattr(_delegate_tls, "config", None)

    if _logger is None or _config is None:
        return {
            "status":          "error",
            "answer":          "Delegate runtime context is not available. Was delegate_subrun called outside an orchestration run?",
            "delegate_prompt": prompt,
            "depth":           _depth,
            "max_iterations":  max_iterations,
        }

    if _depth >= _MAX_DELEGATE_DEPTH:
        return {
            "status":          "error",
            "answer":          f"Maximum delegation depth ({_MAX_DELEGATE_DEPTH}) reached. Cannot delegate further.",
            "delegate_prompt": prompt,
            "depth":           _depth,
            "max_iterations":  max_iterations,
        }

    child_prompt     = f"{instructions}\n\n{prompt}".strip() if instructions else prompt
    child_iterations = max(1, min(int(max_iterations), 8))

    # Build child skills payload - remove Delegate by default to prevent runaway recursion.
    child_payload = copy.deepcopy(_config.skills_payload)
    if not allow_recursive_delegate:
        child_payload["skills"] = [
            s for s in child_payload.get("skills", [])
            if "Delegate" not in s.get("skill_name", "")
        ]

    child_config = OrchestratorConfig(
        resolved_model      = _config.resolved_model,
        num_ctx             = _config.num_ctx,
        max_iterations      = child_iterations,
        skills_payload      = child_payload,
        skills_summary_path = None,
        catalog_mtime       = 0.0,
    )

    _logger.log_file_only(
        f"[delegate] spawning child run: depth={_depth + 1} max_iter={child_iterations} "
        f"prompt={trunc(child_prompt, 80)}"
    )

    try:
        answer, _, _, run_success, _ = orchestrate_prompt(
            user_prompt          = child_prompt,
            config               = child_config,
            logger               = _logger,
            conversation_history = None,
            session_context      = None,
            quiet                = True,
            delegate_depth       = _depth + 1,
        )
        status = "ok" if run_success else "error"
    except Exception as exc:
        answer      = f"Delegate child run failed: {exc}"
        status      = "error"

    return {
        "status":          status,
        "answer":          answer,
        "delegate_prompt": child_prompt,
        "depth":           _depth + 1,
        "max_iterations":  child_iterations,
    }

