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
#   - modes/dashboard.py         -- run_dashboard_mode
#   - skill_executor.py          -- execute_tool_call (executes individual skill calls)
#   - skills_catalog_builder.py  -- build_tool_definitions (generates JSON Schema tool specs)
#   - ollama_client.py           -- call_llm_chat (/v1/chat/completions with tools support)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
from dataclasses import dataclass
from pathlib import Path

from ollama_client import call_llm_chat
from ollama_client import list_ollama_models
from ollama_client import resolve_model_name
from prompt_tokens import resolve_tokens
from runtime_logger import SessionLogger
from skill_executor import execute_tool_call
from skills.Memory.memory_skill import recall_relevant_memories
from skills.Memory.memory_skill import store_prompt_memories
from skills.SystemInfo.system_info_skill import get_system_info_string
from skills_catalog_builder import build_tool_definitions


# ====================================================================================================
# MARK: PATHS
# ====================================================================================================
_SKILLS_SUMMARY_PATH = Path(__file__).resolve().parent / "skills" / "skills_summary.md"


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================
@dataclass
class OrchestratorConfig:
    """Session-level configuration bundle shared by all orchestration calls.

    Passed through the orchestration layer so that adding new session-level settings
    requires only a change to this dataclass and the one construction site in main().
    Fields are intentionally mutable so slash commands (/model, /ctx) can update them
    at runtime without rebuilding the object.
    """
    resolved_model:  str
    num_ctx:         int
    max_iterations:  int
    skills_payload:  dict
    skip_final_llm:  bool = False   # /skip-final sets True; /run-final resets to False


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
    """Truncate *text* to at most *max_words* words, appending ' …' when cut."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


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
            lines = [f"Turn {t['turn']} | user: {t['user_prompt'][:100]}"]
            for o in t["skill_outputs"]:
                skill   = o.get("skill", "?")
                summary = o.get("summary", "")
                lines.append(f"  [{skill}] {summary}")
                for r in o.get("results", []):
                    snippet = r.get("snippet", "")[:80]
                    lines.append(f"    · {r.get('url', '')}  \"{r.get('title', '')}\"  {snippet}")
                if "content" in o:
                    lines.append(f"    {o['content'][:1500]}")
            parts.append("\n".join(lines))

        return "Prior turn skill context (for follow-up reference):\n\n" + "\n\n".join(parts)

    # --------------------------------------------------------------------------

    def _compact_output(self, output: dict) -> dict:
        """Distil a raw skill output dict to a compact, token-efficient summary."""
        module   = Path(output.get("module", "")).stem
        function = output.get("function", "?")
        args     = output.get("arguments", {}) or {}
        result   = output.get("result")

        entry: dict = {"skill": f"{module}.{function}"}
        for key in ("query", "url", "path", "file_path", "domain", "topic"):
            if key in args:
                entry[key] = str(args[key])[:200]
                break

        if result is None:
            entry["summary"] = "(no result)"
        elif isinstance(result, list):
            items = []
            for item in result:
                if isinstance(item, dict):
                    items.append({
                        "url":     item.get("url",     ""),
                        "title":   item.get("title",   ""),
                        "snippet": _truncate_words(
                            item.get("snippet") or item.get("body", ""), 50
                        ),
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
            entry["summary"] = str(result)[:200]

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
        except Exception:
            pass


# ====================================================================================================
# MARK: MODEL RESOLUTION
# ====================================================================================================
def resolve_execution_model(requested_model: str) -> str:
    """Resolve a short alias or tag to a fully-qualified installed Ollama model name.

    Falls back to the first available model (with a printed warning) rather than
    crashing, so a machine with no "20b" model still starts cleanly.
    """
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
# MARK: LOG FORMATTING
# ====================================================================================================
def _format_tool_outputs(tool_outputs: list[dict]) -> str:
    """Return a compact structural summary of executed tool calls and their results."""
    if not tool_outputs:
        return "(no tool calls executed)"

    lines: list[str] = []
    for output in tool_outputs:
        module   = Path(output.get("module", "")).stem
        function = output.get("function", "?")
        args     = output.get("arguments", {}) or {}
        result   = output.get("result")

        lines.append(f"{module}.{function}()")
        for k, v in args.items():
            v_str = repr(v)
            if len(v_str) > 120:
                v_str = v_str[:117] + "..."
            lines.append(f"  {k} = {v_str}")

        if result is None:
            lines.append("  -> None")
        elif isinstance(result, str):
            result_stripped = result.strip()
            preview_lines   = result_stripped.splitlines()[:4]
            total_lines     = result_stripped.count("\n") + 1
            lines.append(f"  -> str  {len(result)} chars / {total_lines} lines")
            for pl in preview_lines:
                if len(pl) > 110:
                    pl = pl[:107] + "..."
                lines.append(f"  {pl}")
            if total_lines > 4:
                lines.append(f"  ... ({total_lines - 4} more lines)")
        elif isinstance(result, dict):
            keys = list(result.keys())
            lines.append(f"  -> dict  [{', '.join(str(k) for k in keys)}]")
        elif isinstance(result, list):
            lines.append(f"  -> list  len={len(result)}")
        else:
            v_str = str(result)[:110]
            lines.append(f"  -> {type(result).__name__}: {v_str}")

        lines.append("")

    return "\n".join(lines)


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

    user_prompt = resolve_tokens(user_prompt)

    _log_section("ORCHESTRATION RUN")
    _log(f"Model:          {config.resolved_model}")
    _log(f"Context window: {config.num_ctx:,} tokens")
    _log(f"Max rounds:     {config.max_iterations}")

    # -- Memory --
    _log_file_only("[progress] Storing prompt memories...")
    memory_store_result = store_prompt_memories(user_prompt=user_prompt)
    _log_file_only("[progress] Recalling relevant memories...")
    recalled_memories   = recall_relevant_memories(user_prompt=user_prompt, limit=5, min_score=0.2)

    _log_section("MEMORY")
    _log(memory_store_result)
    _log(recalled_memories)

    ambient_system_info = get_system_info_string()
    _log_section("AMBIENT SYSTEM INFO")
    _log(ambient_system_info)

    # -- Build tool definitions from the skills catalog --
    tool_defs = build_tool_definitions(config.skills_payload)
    _log_file_only(f"[progress] Tool definitions built: {len(tool_defs)} tools available.")

    # -- Build system message --
    system_parts = [
        "You are a helpful AI assistant with access to tools.",
        "Use tools when they are the appropriate way to answer the user's request - "
        "for real-time data, file operations, task management, computations, and web research.",
        "After using tools, synthesize the results into a clear, direct answer.",
        "Never claim a tool action succeeded unless the tool output explicitly confirms it.",
        "Do not add explanatory preamble - respond with direct answers only.",
        "The current runtime system info (RAM, disk, OS, etc.) is already provided below - "
        "do not call get_system_info_dict unless the user explicitly asks to refresh it.",
    ]
    if ambient_system_info:
        system_parts.append(f"\nRuntime system context:\n{ambient_system_info}")
    if recalled_memories and recalled_memories.strip():
        system_parts.append(f"\nRelevant memories:\n{recalled_memories}")

    _prior_inject = session_context.as_inject_block() if session_context else ""
    if _prior_inject:
        system_parts.append(f"\nPrior session context:\n{_prior_inject}")

    system_message = "\n".join(system_parts)

    # -- Build initial messages list --
    messages: list[dict] = [{"role": "system", "content": system_message}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_prompt})

    # -- Tool calling loop --
    tool_outputs:      list[dict] = []
    prompt_tokens:     int        = 0
    completion_tokens: int        = 0
    final_tps:         float      = 0.0
    run_success:       bool       = False
    final_response:    str        = ""

    for round_num in range(1, config.max_iterations + 1):
        _log_section(f"TOOL ROUND {round_num}")
        _log_file_only(f"[progress] Round {round_num}: calling model...")

        try:
            result = call_llm_chat(
                model_name=config.resolved_model,
                messages=messages,
                tools=tool_defs if tool_defs else None,
                num_ctx=config.num_ctx,
            )
        except Exception as error:
            _log(f"[error] LLM call failed in round {round_num}: {error}")
            final_response = f"(LLM call failed: {error})"
            break

        prompt_tokens     += result.prompt_tokens
        completion_tokens += result.completion_tokens
        final_tps          = result.tokens_per_second

        _log(f"Round {round_num} TPS: {final_tps:.1f} tok/s  ({result.completion_tokens} tokens)")

        if not result.tool_calls:
            # Model answered directly - this is the final response.
            final_response = result.response
            run_success    = bool(final_response)
            _log(final_response)
            _log_file_only(f"[progress] Round {round_num}: model gave final answer.")
            break

        # -- Execute each requested tool call --
        _log(f"Round {round_num}: model requested {len(result.tool_calls)} tool call(s).")
        _log_file_only("[progress] Executing tool calls...")

        messages.append({
            "role":       "assistant",
            "content":    result.response or "",
            "tool_calls": result.tool_calls,
        })

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
                output         = execute_tool_call(func_name, arguments, config.skills_payload, user_prompt)
                result_content = output["result"]
                if not isinstance(result_content, str):
                    result_content = json.dumps(result_content, default=str)
            except Exception as exc:
                result_content = f"Error executing {func_name}: {exc}"
                output = {"function": func_name, "module": "", "arguments": arguments, "result": result_content}

            _log(f"     {str(result_content)[:120]}")
            round_outputs.append(output)
            tool_outputs.append(output)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc_id,
                "name":         func_name,
                "content":      result_content,
            })

        _log_section_file_only(f"TOOL ROUND {round_num} - EXECUTION FLOW")
        _log_file_only(_format_tool_outputs(round_outputs))

        if config.skip_final_llm:
            _log("[skip-final] skip_final_llm set - returning last tool output directly.")
            last           = round_outputs[-1]["result"] if round_outputs else ""
            final_response = last if isinstance(last, str) else json.dumps(last, default=str)
            run_success    = True
            break

    else:
        # Exhausted all rounds without a plain-text answer - request a final synthesis.
        _log("[warn] Max tool rounds exhausted - requesting final synthesis.")
        try:
            result             = call_llm_chat(
                model_name=config.resolved_model,
                messages=messages,
                tools=None,
                num_ctx=config.num_ctx,
            )
            final_response     = result.response
            prompt_tokens     += result.prompt_tokens
            completion_tokens += result.completion_tokens
            final_tps          = result.tokens_per_second
            run_success        = bool(final_response)
            _log_section("FINAL RESPONSE")
            _log(final_response)
        except Exception as error:
            final_response = f"(synthesis failed: {error})"

    _log_section_file_only("TOOL CALL SUMMARY")
    _log_file_only(_format_tool_outputs(tool_outputs))
    _log(f"Total: {prompt_tokens:,} prompt tokens | {completion_tokens:,} completion tokens")

    if session_context is not None and run_success and tool_outputs:
        session_context.add_turn(
            user_prompt=user_prompt,
            assistant_response=final_response,
            skill_outputs=tool_outputs,
        )

    return final_response, prompt_tokens, completion_tokens, run_success, final_tps
