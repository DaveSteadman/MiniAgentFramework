# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Slash-command processor shared across all input modes.
#
# A slash command is any input whose first non-whitespace character is '/'.  Commands are
# dispatched from a registry so new ones can be added by appending to _REGISTRY without
# touching the dispatch logic.
#
# Usage in any calling context:
#
#   from slash_commands import SlashCommandContext, handle as handle_slash
#
#   ctx = SlashCommandContext(
#       config        = config,            # OrchestratorConfig; resolved_model is writable
#       output        = my_output_fn,      # (text: str, level: str = 'info') -> None
#       clear_history = my_clear_fn,       # () -> None  - called when history must be reset
#   )
#   if handle_slash(user_input, ctx):
#       continue   # consumed; skip normal orchestration
#
# Output levels passed to the output callback:
#   'info'    primary response line
#   'item'    list entry / continuation line
#   'error'   failure message
#   'success' confirmation of a state change
#   'dim'     secondary / hint text
#
# Related modules:
#   - main.py           -- creates contexts and calls handle() in API and test-sequence modes
#   - api.py            -- creates context and calls handle() for web UI slash commands
#   - ollama_client.py  -- list_ollama_models, resolve_model_name used by /model commands
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_core.ollama_client import configure_host
from agent_core.ollama_client import get_active_host
from agent_core.ollama_client import get_llm_timeout
from agent_core.ollama_client import get_ollama_ps_rows
from agent_core.ollama_client import is_explicit_model_name
from agent_core.ollama_client import list_ollama_models
from agent_core.ollama_client import register_session_config
from agent_core.ollama_client import resolve_model_name
from agent_core.ollama_client import set_llm_timeout
from agent_core.ollama_client import stop_model
from agent_core.orchestration import compact_context
from agent_core.orchestration import format_context_map
from agent_core.orchestration import get_last_context_map
from agent_core.orchestration import get_last_messages
from agent_core.orchestration import get_sandbox_enabled
from agent_core.orchestration import get_skill_guidance_enabled
from agent_core.orchestration import request_stop
from agent_core.orchestration import set_sandbox_enabled
from agent_core.orchestration import set_skill_guidance_enabled
from agent_core.scratchpad import flush_now
from agent_core.scratchpad import get_dump_enabled
from agent_core.scratchpad import set_dump_enabled
from agent_core.skills.Memory.memory_skill import MEMORY_STORE_LEGACY_PATH
from agent_core.skills.Memory.memory_skill import MEMORY_STORE_PATH
from utils.workspace_utils import get_chatsessions_dir
from utils.workspace_utils import get_chatsessions_named_dir
from utils.workspace_utils import get_controldata_dir
from utils.workspace_utils import get_logs_dir
from utils.workspace_utils import get_schedules_dir
from utils.workspace_utils import get_test_results_dir
from utils.workspace_utils import trunc
from utils.version import __version__


# ====================================================================================================
# MARK: CONTEXT
# ====================================================================================================
@dataclass
class SlashCommandContext:
    """All mutable state and I/O wiring needed by slash command handlers."""
    config:          object                        # OrchestratorConfig; .resolved_model is writable
    output:          Callable[[str, str], None]    # (text, level) -> None
    clear_history:   Callable[[], None]            # resets conversation history + session context
    session_context: object | None = None          # SessionContext; None in non-interactive modes
    session_id:      str | None = None             # current session ID; set in API mode only
    switch_session:  Callable[[str, str], None] | None = None  # (new_session_id, name) -> None
    rename_session:  Callable[[str, str], None] | None = None  # (new_session_id, display_name) -> None; updates browser ID + title in-place


# ====================================================================================================
# MARK: DISPATCH
# ====================================================================================================
def handle(text: str, ctx: SlashCommandContext) -> bool:
    """Process *text* as a slash command.

    Returns True when the input was recognised and handled (caller should skip
    normal orchestration).  Returns False when the input is not a slash command.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False

    parts = stripped.split(None, 1)
    cmd   = parts[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""

    handler = _REGISTRY.get(cmd)
    if handler is None:
        ctx.output(
            f"Unknown command '{cmd}'.  Type /help for available commands.",
            "dim",
        )
        return True

    handler(arg, ctx)
    return True


# ====================================================================================================
# MARK: HANDLERS
# ====================================================================================================
# Handler functions below. Heavy dependencies (skills_catalog_builder, subprocess, sys)
# are still imported locally where they are only needed for specific infrequent commands.
# ====================================================================================================




def _cmd_help(arg: str, ctx: SlashCommandContext) -> None:
    ctx.output("Available slash commands:", "info")
    for name, description in sorted(_DESCRIPTIONS.items()):
        ctx.output(f"  {name:<16} {description}", "item")


# ----------------------------------------------------------------------------------------------------

def _cmd_models(arg: str, ctx: SlashCommandContext) -> None:
    try:
        available = list_ollama_models()
        host = get_active_host()
        ctx.output(f"{len(available)} model(s) installed on: {host}", "info")
        for m in available:
            marker = "\u25ba" if m == ctx.config.resolved_model else " "
            ctx.output(f"  {marker} {m}", "item")
    except Exception as exc:
        ctx.output(f"Error listing models: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_model(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(
            f"Usage: /model <name>  |  current: {ctx.config.resolved_model}",
            "dim",
        )
        return

    try:
        available = list_ollama_models()

        resolved = resolve_model_name(arg, available) if available else None
        if resolved is None:
            if is_explicit_model_name(arg):
                resolved = arg.strip()
                ctx.output(
                    f"Model '{resolved}' is not in the downloaded model list; using it as an explicit override.",
                    "dim",
                )
            else:
                if not available:
                    ctx.output("No models installed in Ollama.", "error")
                    return
                ctx.output(
                    f"Model '{arg}' not found.  Available: {', '.join(available)}",
                    "error",
                )
                return

        old = ctx.config.resolved_model
        ctx.config.resolved_model = resolved
        register_session_config(resolved, ctx.config.num_ctx)
        ctx.clear_history()
        ctx.output(f"Model switched: {old} \u2192 {resolved}", "success")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        ctx.output(f"Error: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_ctx(arg: str, ctx: SlashCommandContext) -> None:
    # Shared helpers used by multiple subcommands.
    def _get_map_and_messages():
        return get_last_context_map(), get_last_messages()

    def _show_map(context_map):
        ctx.output(format_context_map(context_map, ctx.config.num_ctx), "item")

    def _resolve_index(rest: str) -> tuple[list, list, int] | None:
        # Validate and parse a context-map index string.
        # Returns (context_map, messages, idx) on success; outputs an error and returns None on failure.
        context_map, messages = _get_map_and_messages()
        if not context_map:
            ctx.output("No run context available - send a prompt first.", "error")
            return None
        try:
            idx = int(rest)
        except ValueError:
            ctx.output(f"Invalid index '{rest}' - must be an integer.", "error")
            return None
        if idx < 0 or idx >= len(context_map):
            ctx.output(f"Index {idx} out of range (0 - {len(context_map) - 1}).", "error")
            return None
        return context_map, messages, idx

    # /ctx - show map + window size.
    if not arg:
        context_map, _ = _get_map_and_messages()
        if context_map:
            _show_map(context_map)
            ctx.output("", "dim")
        ctx.output(f"Context window size: {ctx.config.num_ctx:,} tokens", "info")
        return

    parts = arg.split(None, 1)
    sub   = parts[0].lower()
    rest  = parts[1].strip() if len(parts) > 1 else ""

    # /ctx size [<num>] - show or set window size.
    if sub == "size":
        if not rest:
            ctx.output(f"Context window size: {ctx.config.num_ctx:,} tokens", "info")
            return
        try:
            value = int(rest.replace(",", "").replace("_", ""))
        except ValueError:
            ctx.output(f"Invalid value '{rest}' - must be an integer (e.g. /ctx size 32768).", "error")
            return
        if value < 512:
            ctx.output("Context size must be at least 512 tokens.", "error")
            return
        old = ctx.config.num_ctx
        ctx.config.num_ctx = value
        register_session_config(ctx.config.resolved_model, value)
        ctx.output(f"Context window size changed: {old:,} \u2192 {value:,}", "success")
        return

    # /ctx item <num> - show raw message content at map index N.
    if sub == "item":
        if not rest:
            ctx.output("Usage: /ctx item <index>", "dim")
            return
        resolved = _resolve_index(rest)
        if resolved is None:
            return
        context_map, messages, idx = resolved
        entry   = context_map[idx]
        msg_idx = entry.get("msg_idx")
        ctx.output(f"Entry {idx}: role={entry.get('role')}  label={entry.get('label')}  chars={entry.get('chars'):,}", "info")
        if msg_idx is None:
            ctx.output("(no associated message - not individually addressable)", "dim")
            return
        content = messages[msg_idx].get("content") or ""
        ctx.output(content if content else "(empty)", "item")
        return

    # /ctx compact <num> - compact map entry N showing before/after.
    if sub == "compact":
        if not rest:
            ctx.output("Usage: /ctx compact <index>", "dim")
            return
        resolved = _resolve_index(rest)
        if resolved is None:
            return
        context_map, messages, idx = resolved
        entry = context_map[idx]
        if entry.get("msg_idx") is None:
            ctx.output(
                f"Entry {idx} ({entry.get('role')} / {entry.get('label')}) has no associated message - cannot compact.",
                "error",
            )
            return
        ctx.output("Before:", "dim")
        _show_map(context_map)
        changed = compact_context(context_map, messages, idx)
        if not changed:
            ctx.output(f"Entry {idx} was already compacted.", "dim")
            return
        ctx.output("", "dim")
        ctx.output("After:", "dim")
        _show_map(context_map)
        return

    ctx.output(
        f"Unknown sub-command '{sub}'.  Usage: /ctx | /ctx size [<n>] | /ctx item <n> | /ctx compact <n>",
        "error",
    )


# ----------------------------------------------------------------------------------------------------

def _cmd_rounds(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(
            f"Usage: /rounds <n>  |  current: {ctx.config.max_iterations}",
            "dim",
        )
        return
    try:
        value = int(arg.strip())
    except ValueError:
        ctx.output(f"Invalid value '{arg}' - must be a positive integer (e.g. /rounds 6).", "error")
        return
    if value < 1:
        ctx.output("Rounds must be at least 1.", "error")
        return
    old = ctx.config.max_iterations
    ctx.config.max_iterations = value
    ctx.output(f"Max tool rounds changed: {old} \u2192 {value}", "success")


# ----------------------------------------------------------------------------------------------------

def _cmd_timeout(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(
            f"Usage: /timeout <seconds>  |  current: {get_llm_timeout()}s",
            "dim",
        )
        return
    try:
        value = int(arg.strip().replace(",", "").replace("_", ""))
    except ValueError:
        ctx.output(f"Invalid value '{arg}' - must be an integer number of seconds (e.g. /timeout 1800).", "error")
        return
    if value < 10:
        ctx.output("Timeout must be at least 10 seconds.", "error")
        return
    old = get_llm_timeout()
    set_llm_timeout(value)
    ctx.output(f"LLM timeout changed: {old}s \u2192 {value}s", "success")


# ----------------------------------------------------------------------------------------------------

def _cmd_stopmodel(arg: str, ctx: SlashCommandContext) -> None:

    # Determine which model to stop: explicit arg, or fall back to the active model.
    target_name = arg.strip() if arg.strip() else ctx.config.resolved_model

    # Resolve against currently running models so we get the exact full tag.
    try:
        running_rows = get_ollama_ps_rows()
    except Exception as exc:
        ctx.output(f"Error reading running models: {exc}", "error")
        return

    running_names = [row.get("name", "") for row in running_rows if row.get("name")]

    if not running_names:
        ctx.output("No models are currently loaded in Ollama.", "dim")
        return

    resolved = resolve_model_name(target_name, running_names)
    if resolved is None:
        ctx.output(
            f"Model '{target_name}' is not currently loaded.  Running: {', '.join(running_names)}",
            "error",
        )
        return

    try:
        stop_model(resolved)
        ctx.output(f"Model unloaded: {resolved}", "success")
    except Exception as exc:
        ctx.output(f"Error stopping model: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_scratchdump(arg: str, ctx: SlashCommandContext) -> None:
    sub = arg.strip().lower()
    if sub == "on":
        set_dump_enabled(True)
        dump_path = get_controldata_dir() / "scratchpad_dump.txt"
        ctx.output("Scratchpad file dump enabled.", "success")
        ctx.output(f"  Writing to: {dump_path}", "dim")
        ctx.output("  File is overwritten on every scratch_save / scratch_delete / scratch_clear.", "dim")
        flush_now()   # write current state immediately so user can confirm the file exists
    elif sub == "off":
        set_dump_enabled(False)
        ctx.output("Scratchpad file dump disabled.", "success")
    else:
        state = "on" if get_dump_enabled() else "off"
        ctx.output(f"Usage: /scratchdump <on|off>  |  current: {state}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_newchat(arg: str, ctx: SlashCommandContext) -> None:
    ctx.clear_history()
    ctx.output("Conversation history cleared - starting a new chat.", "success")


# ----------------------------------------------------------------------------------------------------

def _cmd_clearmemory(arg: str, ctx: SlashCommandContext) -> None:
    store_path  = MEMORY_STORE_PATH
    legacy_path = MEMORY_STORE_LEGACY_PATH

    deleted = []
    for path in (store_path, legacy_path):
        if path.exists():
            path.unlink()
            deleted.append(path.name)

    if deleted:
        ctx.output(f"Memory store cleared ({', '.join(deleted)} deleted).", "success")
    else:
        ctx.output("Memory store was already empty.", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_reskills(arg: str, ctx: SlashCommandContext) -> None:
    sub = arg.strip().lower()

    # Handle mode-only calls (no rebuild needed).
    if sub == "max":
        set_skill_guidance_enabled(True)
        ctx.output("Skill guidance mode: max (tool selection block included in system prompt).", "success")
        ctx.output("  ~925 extra tokens per call.  Good for comparison testing.", "dim")
        return
    if sub == "min":
        set_skill_guidance_enabled(False)
        ctx.output("Skill guidance mode: min (tool selection block omitted from system prompt).", "success")
        ctx.output("  Relies on JSON Schema tool descriptions only.", "dim")
        return
    if sub and sub not in ("min", "max", ""):
        current = "max" if get_skill_guidance_enabled() else "min"
        ctx.output(f"Usage: /reskill [min|max]  |  current mode: {current}", "dim")
        ctx.output("  min  - lean system prompt; no tool selection guidance block (default)", "dim")
        ctx.output("  max  - full guidance block injected for comparison testing", "dim")
        return

    # No arg (or empty): rebuild catalog and default to min.
    if not sub:
        set_skill_guidance_enabled(False)

    current_mode = "max" if get_skill_guidance_enabled() else "min"
    ctx.output(f"Rebuilding skills catalog (local extraction, no LLM) - mode: {current_mode}...", "dim")
    try:
        from agent_core.skills_catalog_builder import DEFAULT_OUTPUT_FILE
        from agent_core.skills_catalog_builder import DEFAULT_SKILLS_ROOT
        from agent_core.skills_catalog_builder import find_skill_files
        from agent_core.skills_catalog_builder import load_skills_payload
        from agent_core.skills_catalog_builder import normalize_summary
        from agent_core.skills_catalog_builder import render_summary_document
        from agent_core.skills_catalog_builder import summarize_skill

        skills_root = DEFAULT_SKILLS_ROOT
        output_path = DEFAULT_OUTPUT_FILE
        skill_files = find_skill_files(skills_root=skills_root)
        if not skill_files:
            ctx.output("No skill.md files found - catalog unchanged.", "error")
            return

        summaries = [
            normalize_summary(
                summarize_skill(f, use_llm=False, model_name="", num_ctx=0),
                f,
            )
            for f in skill_files
        ]
        summary_text = render_summary_document(summaries=summaries, output_path=output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(summary_text, encoding="utf-8")

        # Hot-reload into the live config so this session immediately picks up the changes.
        ctx.config.skills_payload = load_skills_payload(output_path)
        ctx.output(
            f"Skills catalog rebuilt: {len(summaries)} skill(s) registered.  Mode: {current_mode}.",
            "success",
        )
    except Exception as exc:
        ctx.output(f"Error rebuilding skills catalog: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_recall(arg: str, ctx: SlashCommandContext) -> None:
    sc = ctx.session_context
    if sc is None:
        ctx.output("No session context available in this mode.", "error")
        return

    n = sc.turn_count()
    if n == 0:
        ctx.output("Session context is empty - no skill outputs stored yet.", "dim")
        return

    ctx.output(f"Session context: {n} turn(s) stored", "info")
    for t in sc.get_turns():
        ctx.output(f"  Turn {t['turn']}: {trunc(t['user_prompt'], 80)}", "item")
        for o in t["skill_outputs"]:
            skill   = o.get("skill", "?")
            summary = o.get("summary", "")
            url     = o.get("url", "")
            extra   = f"  url: {url}" if url else ""
            ctx.output(f"    [{skill}] {summary}{extra}", "dim")
            for r in o.get("results", []):
                ctx.output(f"      \u00b7 {r.get('url', '')}  {trunc(r.get('title', ''), 60)}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_stoprun(arg: str, ctx: SlashCommandContext) -> None:
    # In API mode this command is intercepted and handled by api.py before it reaches here,
    # so this stub only runs in non-API contexts (e.g. TUI, tests).
    # It sets the orchestration stop event so the active run exits after its current round.
    request_stop()
    ctx.output("Stop requested. Active run will halt after its current LLM round.", "info")


# ----------------------------------------------------------------------------------------------------

def _cmd_kiwixhost(arg: str, ctx: SlashCommandContext) -> None:
    defaults_path = get_controldata_dir() / "default.json"

    def _load_defaults() -> dict:
        try:
            return json.loads(defaults_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    if not arg:
        current = _load_defaults().get("kiwixurl", "(not set)")
        ctx.output(f"Usage: /kiwixhost <url>  |  current: {current}", "dim")
        return

    raw = arg.strip().rstrip("/")
    if "://" not in raw:
        raw = f"http://{raw}"

    # Verify the host responds before saving.
    try:
        req = urllib.request.Request(f"{raw}/", method="HEAD")
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        ctx.output(f"Cannot reach '{raw}': {exc}", "error")
        ctx.output("Kiwix host not changed.", "dim")
        return

    cfg = _load_defaults()
    old = cfg.get("kiwixurl", "(not set)")
    cfg["kiwixurl"] = raw
    try:
        defaults_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        ctx.output(f"Error saving default.json: {exc}", "error")
        return

    ctx.output(f"Kiwix host updated: {old} -> {raw}", "success")
    ctx.output("Takes effect immediately - no restart required.", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_host(arg: str, ctx: SlashCommandContext) -> None:

    if not arg:
        ctx.output(
            f"Usage: /ollamahost <hostname|url|local>  |  current: {get_active_host()}",
            "dim",
        )
        return

    raw      = arg.strip()
    old_host = get_active_host()

    try:
        configure_host(raw)
        new_host = get_active_host()
        models   = list_ollama_models()
        ctx.clear_history()
        ctx.output(f"Host switched: {old_host} \u2192 {new_host}", "success")
        if models:
            ctx.output(f"  {len(models)} model(s): {', '.join(models)}", "item")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        configure_host(old_host)
        ctx.output(f"Cannot reach '{raw}': {exc}", "error")
        ctx.output(f"Still using: {old_host}", "dim")


# ----------------------------------------------------------------------------------------------------

def _run_one_test_file(
    candidate,
    ctx,
    wrapper,
    model: str,
    active_host: str,
    re_mod,
    subprocess_mod,
    sys_mod,
    output_file=None,
) -> dict:
    # Run a single test file via test_wrapper.py and stream output to ctx.
    # Returns parsed test metrics for summary output.
    cmd = [
        sys_mod.executable, str(wrapper),
        "--prompts-file", str(candidate),
        "--model", model,
    ]
    if "localhost" not in active_host and "127.0.0.1" not in active_host:
        cmd += ["--ollamahost", active_host]
    if output_file is not None:
        cmd += ["--output-file", str(output_file)]
    cmd += ["--source-file", candidate.name]

    _summary_re = re_mod.compile(r"^\[TEST_SUMMARY\] passed=(\d+) total=(\d+)$")
    _metrics_re = re_mod.compile(r"^\[TURN\s+(\d+)\]\s+tokens=(\d+)\s+tps=([0-9.]+)$")
    test_passed = test_total = None
    prompt_tokens_total = 0
    tps_sum             = 0.0
    tps_samples         = 0
    try:
        proc = subprocess_mod.Popen(
            cmd,
            stdout=subprocess_mod.PIPE,
            stderr=subprocess_mod.STDOUT,
            text=True,
            encoding="utf-8",
        )
        # Watcher thread: kill the subprocess promptly when /stoprun is requested.
        # test_wrapper runs the full orchestration pipeline in a child process so the
        # orchestration stop-event is not visible here - we must terminate the OS process.
        import threading as _threading
        import time as _time
        _stopped_by_user = [False]
        _watcher_done    = [False]

        def _watch(_p=proc) -> None:
            from agent_core.orchestration import is_stop_requested
            while not _watcher_done[0]:
                if is_stop_requested():
                    _stopped_by_user[0] = True
                    try:
                        _p.terminate()
                    except Exception:
                        pass
                    return
                _time.sleep(0.2)

        _wt = _threading.Thread(target=_watch, daemon=True)
        _wt.start()
        try:
            for line in proc.stdout:
                stripped = line.rstrip()
                m = _summary_re.match(stripped)
                if m:
                    test_passed = int(m.group(1))
                    test_total  = int(m.group(2))
                    continue
                metrics_match = _metrics_re.match(stripped)
                if metrics_match:
                    prompt_tokens_total += int(metrics_match.group(2))
                    turn_tps = float(metrics_match.group(3))
                    if turn_tps > 0:
                        tps_sum     += turn_tps
                        tps_samples += 1
                    continue
                if stripped:
                    ctx.output(stripped, "dim")
            proc.wait()
        finally:
            _watcher_done[0] = True
            _wt.join(timeout=1.0)

        if _stopped_by_user[0]:
            ctx.output("[Test stopped by /stoprun]", "error")
            return {
                "passed":        0,
                "total":         0,
                "prompt_tokens": prompt_tokens_total,
                "tps_sum":       tps_sum,
                "tps_samples":   tps_samples,
            }
    except Exception as exc:
        ctx.output(f"Error running {candidate.name}: {exc}", "error")
        return {
            "passed":        0,
            "total":         0,
            "prompt_tokens": 0,
            "tps_sum":       0.0,
            "tps_samples":   0,
        }

    if test_passed is not None:
        level = "success" if test_passed == test_total else "error"
        ctx.output(f"[Test: {candidate.name}  Passed {test_passed}/{test_total}]", level)
        pass_rate = (100.0 * test_passed / test_total) if test_total else 0.0
        avg_tps   = (tps_sum / tps_samples) if tps_samples else 0.0
        ctx.output(
            f"[TEST COMPLETE] {candidate.name} | pass rate={pass_rate:.0f}% ({test_passed}/{test_total})"
            f" | prompt tokens={prompt_tokens_total:,} | avg tok/s={avg_tps:.1f}",
            level,
        )
        return {
            "passed":        test_passed,
            "total":         test_total,
            "prompt_tokens": prompt_tokens_total,
            "tps_sum":       tps_sum,
            "tps_samples":   tps_samples,
        }
    elif proc.returncode == 0:
        ctx.output(f"[Test: {candidate.name}  completed (no summary)]", "dim")
    else:
        ctx.output(f"[Test: {candidate.name}  exited with code {proc.returncode}]", "error")
    return {
        "passed":        0,
        "total":         0,
        "prompt_tokens": prompt_tokens_total,
        "tps_sum":       tps_sum,
        "tps_samples":   tps_samples,
    }


# ----------------------------------------------------------------------------------------------------
def _run_post_test_checks(ctx, csv_path, testcode_dir, subprocess_mod, sys_mod) -> None:
    # Run quick unit tests and the results analyzer after a wrapper test run completes.
    # Runs test_regressions.py and test_thinking_strip.py (no LLM, completes in seconds),
    # then test_analyzer.py on the CSV to produce _analysis.csv and _gaps.txt alongside it.
    ctx.output("--- Post-test checks ---", "dim")
    for script_name in ("test_regressions.py", "test_thinking_strip.py"):
        script = testcode_dir / script_name
        ctx.output(f"  {script_name} ...", "dim")
        try:
            proc = subprocess_mod.run(
                [sys_mod.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            combined = (proc.stdout + proc.stderr).strip()
            for line in combined.splitlines():
                ctx.output(f"    {line}", "dim" if proc.returncode == 0 else "error")
            level = "success" if proc.returncode == 0 else "error"
            ctx.output(f"  [{script_name}: {'OK' if proc.returncode == 0 else 'FAILED'}]", level)
        except Exception as exc:
            ctx.output(f"  Error running {script_name}: {exc}", "error")
    if csv_path is not None and csv_path.exists():
        analyzer = testcode_dir / "test_analyzer.py"
        ctx.output(f"  test_analyzer on {csv_path.name} ...", "dim")
        try:
            proc = subprocess_mod.run(
                [sys_mod.executable, str(analyzer), str(csv_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            for line in (proc.stdout + proc.stderr).splitlines():
                ctx.output(f"    {line}", "dim" if proc.returncode == 0 else "error")
        except Exception as exc:
            ctx.output(f"  Error running test_analyzer: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_test(arg: str, ctx: SlashCommandContext) -> None:
    import re
    import subprocess
    import sys
    import time
    from datetime import datetime

    test_prompts_dir = Path(__file__).resolve().parent.parent.parent / "controldata" / "test_prompts"
    wrapper          = Path(__file__).resolve().parent.parent / "testing" / "test_wrapper.py"

    if not arg:
        ctx.output(
            "Usage: /test <prompts-file|all>  (filename from controldata/test_prompts/ or full path)",
            "dim",
        )
        if test_prompts_dir.exists():
            files = sorted(test_prompts_dir.glob("*.json"))
            if files:
                ctx.output("Available files:", "info")
                for f in files:
                    ctx.output(f"  {f.name}", "item")
        return

    # ---- /test all ----
    if arg.strip().lower() == "all":
        if not test_prompts_dir.exists():
            ctx.output("Test prompts directory not found.", "error")
            return
        all_files = sorted(test_prompts_dir.glob("*.json"))
        if not all_files:
            ctx.output("No test files found.", "error")
            return

        def _run_all(
            _files=list(all_files),
            _wrapper=wrapper,
            _ctx=ctx,
        ) -> None:
            _model = _ctx.config.resolved_model
            _host  = get_active_host()
            # Pre-allocate a single shared CSV file for all test files in this run.
            _now = datetime.now()
            _shared_output = (
                get_test_results_dir()
                / _now.strftime("%Y-%m-%d")
                / f"test_results_{_now.strftime('%Y%m%d_%H%M%S')}_all.csv"
            )
            _shared_output.parent.mkdir(parents=True, exist_ok=True)
            _ctx.output(
                f"Running all {len(_files)} test file(s) - host: {_host}  model: {_model}",
                "info",
            )
            _ctx.output(f"Results file: {_shared_output}", "dim")
            total_passed = 0
            total_tests  = 0
            total_prompt_tokens = 0
            total_tps_sum       = 0.0
            total_tps_samples   = 0
            wall_start   = time.monotonic()
            _bar = "=" * 47
            for idx, candidate in enumerate(_files, start=1):
                _ctx.output(_bar, "info")
                _ctx.output(f"= Test Suite: {candidate.stem}", "info")
                _ctx.output(_bar, "info")
                _ctx.output(f"[{idx}/{len(_files)}] Starting: {candidate.name}", "info")
                result = _run_one_test_file(
                    candidate, _ctx, _wrapper, _model, _host, re, subprocess, sys,
                    output_file=_shared_output,
                )
                total_passed       += result["passed"]
                total_tests        += result["total"]
                total_prompt_tokens += result["prompt_tokens"]
                total_tps_sum      += result["tps_sum"]
                total_tps_samples  += result["tps_samples"]
            elapsed   = time.monotonic() - wall_start
            mins, sec = divmod(int(elapsed), 60)
            time_str  = f"{mins}m {sec}s" if mins else f"{sec}s"
            level     = "success" if total_passed == total_tests and total_tests > 0 else "error"
            pass_rate = (100.0 * total_passed / total_tests) if total_tests else 0.0
            avg_tps   = (total_tps_sum / total_tps_samples) if total_tps_samples else 0.0
            _ctx.output(
                f"[ALL TESTS COMPLETE]  host={_host}  model={_model}  "
                f"elapsed={time_str}  pass rate={pass_rate:.0f}% ({total_passed}/{total_tests})"
                f"  prompt tokens={total_prompt_tokens:,}  avg tok/s={avg_tps:.1f}",
                level,
            )
            _run_post_test_checks(_ctx, _shared_output, _wrapper.parent, subprocess, sys)

        _run_all()
        return

    # ---- single file ----
    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = test_prompts_dir / arg
        if not candidate.suffix:
            candidate = candidate.with_suffix(".json")

    if not candidate.exists():
        # Try substring match against available files.
        if test_prompts_dir.exists():
            matches = sorted(f for f in test_prompts_dir.glob("*.json") if arg.lower() in f.stem.lower())
            if matches:
                candidate = matches[0]
                ctx.output(f"Matched: {candidate.name}", "dim")
            else:
                ctx.output(f"No test file matching '{arg}' found.", "error")
                return
        else:
            ctx.output(f"Prompts file not found: {candidate}", "error")
            return

    def _run_single(
        _candidate=candidate,
        _wrapper=wrapper,
        _ctx=ctx,
        _datetime=datetime,
    ) -> None:
        _model = _ctx.config.resolved_model
        _host  = get_active_host()
        _now   = _datetime.now()
        _output_file = (
            get_test_results_dir()
            / _now.strftime("%Y-%m-%d")
            / f"test_results_{_now.strftime('%Y%m%d_%H%M%S')}_{_candidate.stem}.csv"
        )
        _output_file.parent.mkdir(parents=True, exist_ok=True)
        _ctx.output(f"Running test suite: {_candidate.name} ...", "info")
        _run_one_test_file(
            _candidate, _ctx, _wrapper, _model, _host, re, subprocess, sys,
            output_file=_output_file,
        )
        _run_post_test_checks(_ctx, _output_file, _wrapper.parent, subprocess, sys)

    _run_single()


# ----------------------------------------------------------------------------------------------------

def _cmd_testtrend(arg: str, ctx: SlashCommandContext) -> None:
    # Scan raw test result CSVs under controldata/test_results/, optionally filtered
    # by prompts-file name, sort chronologically, and print a pass-rate table.
    # Pass/fail is computed from assert_result + exit_code in the raw CSV so the
    # numbers stay accurate even for runs predating the _analysis.csv assert fix.
    # If a companion _analysis.csv exists it is used only for iterations_used (AvgRnds).
    import csv
    import re
    from pathlib import Path
    from utils.workspace_utils import get_test_results_dir

    results_root = get_test_results_dir()
    if not results_root.exists():
        ctx.output("No test results directory found.", "error")
        return

    filter_name = arg.strip().lower().replace(" ", "_") if arg.strip() else ""

    # Filename pattern: test_results_YYYYMMDD_HHMMSS_<prompts_name>.csv
    # Skip _analysis and _gaps files.
    _fname_re = re.compile(r"^test_results_(\d{8}_\d{6})_(.+?)\.csv$")

    entries: list[tuple[str, str, Path]] = []  # (sort_key, prompts_name, raw_csv_path)
    for csv_path in results_root.rglob("*.csv"):
        if "_analysis" in csv_path.stem or "_gaps" in csv_path.stem:
            continue
        m = _fname_re.match(csv_path.name)
        if not m:
            continue
        ts_key       = m.group(1)   # YYYYMMDD_HHMMSS - sorts lexicographically
        prompts_name = m.group(2)
        if filter_name and filter_name not in prompts_name:
            continue
        entries.append((ts_key, prompts_name, csv_path))

    if not entries:
        hint = f" matching '{filter_name}'" if filter_name else ""
        ctx.output(f"No test result files found{hint}.", "dim")
        return

    entries.sort(key=lambda e: e[0])

    # Determine whether the prompts-file column is needed (mixed files in results)
    show_file_col = len({e[1] for e in entries}) > 1

    # ---- header ----
    if show_file_col:
        ctx.output(
            f"{'Timestamp':<18}  {'Prompts file':<28}  {'Total':>5}  {'Pass%':>6}  "
            f"{'Fail':>4}  {'Gap':>4}  {'AvgRnds':>7}  {'AvgSec':>6}  {'Runtime':<9}",
            "info",
        )
    else:
        label = entries[0][1] if entries else ""
        ctx.output(f"Trend for: {label}", "info")
        ctx.output(
            f"{'Timestamp':<18}  {'Total':>5}  {'Pass%':>6}  {'Fail':>4}  "
            f"{'Gap':>4}  {'AvgRnds':>7}  {'AvgSec':>6}  {'Runtime':<9}",
            "info",
        )

    ctx.output("-" * (90 if show_file_col else 75), "dim")

    # ---------------------------------------------------------------------------
    def _row_outcome(r: dict) -> str:
        # Determine PASS/FAIL/GAP for a single raw CSV row.
        # assert_result is authoritative when present; fall back to exit_code check.
        assert_r = r.get("assert_result", "").strip().upper()
        if assert_r == "FAIL":
            return "FAIL"
        if assert_r == "PASS":
            return "PASS"
        # No assert - use exit_code and output presence
        try:
            code = int(r.get("exit_code", "0"))
        except (ValueError, TypeError):
            code = -1
        if code != 0:
            return "FAIL"
        if not r.get("final_output", "").strip():
            return "FAIL"
        return "PASS"

    # ---------------------------------------------------------------------------
    def _fmt_runtime(total_seconds: float) -> str:
        total_int = int(total_seconds)
        mins, secs = divmod(total_int, 60)
        if mins:
            return f"{mins}m {secs:02d}s"
        return f"{secs}s"

    # ---------------------------------------------------------------------------
    for ts_key, prompts_name, raw_csv_path in entries:
        # Parse timestamp into a readable form: YYYYMMDD_HHMMSS -> YYYY-MM-DD HH:MM
        ts_display = f"{ts_key[:4]}-{ts_key[4:6]}-{ts_key[6:8]} {ts_key[9:11]}:{ts_key[11:13]}"

        raw_rows: list[dict] = []
        try:
            with raw_csv_path.open(newline="", encoding="utf-8") as f:
                raw_rows = list(csv.DictReader(f))
        except OSError:
            ctx.output(f"  {ts_display}  (unreadable)", "error")
            continue

        if not raw_rows:
            ctx.output(f"  {ts_display}  (empty)", "dim")
            continue

        # Pass/fail counts from raw CSV
        outcomes = [_row_outcome(r) for r in raw_rows]
        total    = len(outcomes)
        passes   = outcomes.count("PASS")
        fails    = outcomes.count("FAIL")
        gaps     = outcomes.count("GAP")
        pass_pct = 100.0 * passes / total if total else 0.0

        # Runtime totals from raw CSV
        dur_vals: list[float] = []
        for r in raw_rows:
            try:
                dur_vals.append(float(r.get("duration_seconds", 0)))
            except (ValueError, TypeError):
                pass
        total_secs = sum(dur_vals)
        avg_dur    = total_secs / len(dur_vals) if dur_vals else 0.0

        # iterations_used comes from the companion _analysis.csv if it exists
        iter_vals: list[float] = []
        analysis_path = raw_csv_path.with_name(f"{raw_csv_path.stem}_analysis.csv")
        if analysis_path.exists():
            try:
                with analysis_path.open(newline="", encoding="utf-8") as f:
                    for ar in csv.DictReader(f):
                        try:
                            iter_vals.append(float(ar.get("iterations_used", 0)))
                        except (ValueError, TypeError):
                            pass
            except OSError:
                pass
        avg_rounds = sum(iter_vals) / len(iter_vals) if iter_vals else 0.0

        runtime_str    = _fmt_runtime(total_secs)
        outcome_marker = "" if passes == total else " !"
        level          = "success" if passes == total else "error" if fails > 0 else "dim"

        if show_file_col:
            ctx.output(
                f"{ts_display:<18}  {prompts_name:<28}  {total:>5}  {pass_pct:>5.0f}%  "
                f"{fails:>4}  {gaps:>4}  {avg_rounds:>7.1f}  {avg_dur:>6.1f}  {runtime_str:<9}{outcome_marker}",
                level,
            )
        else:
            ctx.output(
                f"{ts_display:<18}  {total:>5}  {pass_pct:>5.0f}%  {fails:>4}  "
                f"{gaps:>4}  {avg_rounds:>7.1f}  {avg_dur:>6.1f}  {runtime_str:<9}{outcome_marker}",
                level,
            )


# ----------------------------------------------------------------------------------------------------

def _cmd_version(arg: str, ctx: SlashCommandContext) -> None:
    ctx.output(f"MiniAgentFramework {__version__}", "info")

# ----------------------------------------------------------------------------------------------------
def _cmd_sandbox(arg: str, ctx: SlashCommandContext) -> None:
    sub = arg.strip().lower()
    if sub == "on":
        set_sandbox_enabled(True)
        ctx.output("Python sandbox enabled - imports restricted to the safe whitelist.", "success")
    elif sub == "off":
        set_sandbox_enabled(False)
        ctx.output("Python sandbox disabled - code snippets run with full Python access.", "success")
        ctx.output("Warning: /sandbox off allows unrestricted code execution. Re-enable with /sandbox on.", "dim")
    else:
        state = "on" if get_sandbox_enabled() else "off"
        ctx.output(f"Usage: /sandbox <on|off>  |  current: {state}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_deletelogs(arg: str, ctx: SlashCommandContext) -> None:
    import re
    import shutil
    from datetime import date
    from datetime import timedelta
    from utils.workspace_utils import get_chatsessions_dir
    from utils.workspace_utils import get_logs_dir
    from utils.workspace_utils import get_test_results_dir

    if not arg.strip():
        ctx.output("Usage: /deletelogs <days>  |  delete log, chatsession, and test_results date-folders older than N days (named sessions are never culled)", "dim")
        return

    try:
        days = int(arg.strip())
    except ValueError:
        ctx.output(f"Invalid value '{arg}' - must be an integer number of days.", "error")
        return

    if days < 1:
        ctx.output("Days must be at least 1.", "error")
        return

    cutoff  = date.today() - timedelta(days=days)
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    deleted = []
    errors  = []

    for base_dir in (get_logs_dir(), get_chatsessions_dir(), get_test_results_dir()):
        if not base_dir.exists():
            continue
        for folder in sorted(base_dir.iterdir()):
            if not folder.is_dir() or not date_re.match(folder.name):
                continue
            try:
                folder_date = date.fromisoformat(folder.name)
            except ValueError:
                continue
            if folder_date <= cutoff:
                try:
                    shutil.rmtree(folder)
                    deleted.append(f"{base_dir.name}/{folder.name}")
                except Exception as exc:
                    errors.append(f"{base_dir.name}/{folder.name}: {exc}")

    stray_deleted = []
    stray_errors  = []

    # Delete stray files from logs/, test_results/, and chatsessions/ root unconditionally.
    # Named sessions live in chatsessions/named/ (a subdirectory) and are never touched.
    for base_dir in (get_logs_dir(), get_test_results_dir(), get_chatsessions_dir()):
        if not base_dir.exists():
            continue
        for item in sorted(base_dir.iterdir()):
            if item.is_file():
                try:
                    item.unlink()
                    stray_deleted.append(f"{base_dir.name}/{item.name}")
                except Exception as exc:
                    stray_errors.append(f"{base_dir.name}/{item.name}: {exc}")

    if deleted:
        ctx.output(f"Deleted {len(deleted)} date-folder(s):", "success")
        for entry in deleted:
            ctx.output(f"  {entry}", "item")
    else:
        ctx.output(f"No date-folders older than {days} day(s) found.", "dim")
    if stray_deleted:
        ctx.output(f"Deleted {len(stray_deleted)} stray file(s):", "success")
        for entry in stray_deleted:
            ctx.output(f"  {entry}", "item")
    for err in errors + stray_errors:
        ctx.output(f"Error deleting {err}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_tasks(arg: str, ctx: SlashCommandContext) -> None:
    """List all scheduled tasks from every JSON file in the schedules directory."""
    import json
    from utils.workspace_utils import get_schedules_dir

    schedules_dir = get_schedules_dir()
    if not schedules_dir.exists():
        ctx.output("Schedules directory not found.", "error")
        return

    json_files = sorted(schedules_dir.glob("*.json"))
    if not json_files:
        ctx.output("No schedule files found.", "dim")
        return

    total = 0
    for json_path in json_files:
        try:
            data  = json.loads(json_path.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
        except Exception as exc:
            ctx.output(f"  {json_path.name}: read error ({exc})", "error")
            continue
        for task in tasks:
            name     = task.get("name", "?")
            enabled  = task.get("enabled", True)
            schedule = task.get("schedule", {})
            stype    = schedule.get("type", "?")
            if stype == "interval":
                sched_str = f"every {schedule.get('minutes', '?')} min"
            elif stype == "daily":
                sched_str = f"daily @ {schedule.get('time', '?')}"
            else:
                sched_str = stype
            prompts   = task.get("prompts", [])
            status    = "on " if enabled else "off"
            first_p   = trunc(prompts[0], 60) if prompts else "(no prompts)"
            ctx.output(f"  [{status}]  {name:<28}  {sched_str:<18}  {first_p}", "item")
            total += 1

    ctx.output(f"{total} task(s) across {len(json_files)} file(s).", "info")


# ----------------------------------------------------------------------------------------------------

def _task_find(name: str) -> "tuple | None":
    """Locate a task by name.  Returns (json_path, data, task_index) or None."""
    import json
    from utils.workspace_utils import get_schedules_dir

    schedules_dir = get_schedules_dir()
    if not schedules_dir.exists():
        return None

    for json_path in sorted(schedules_dir.glob("*.json")):
        try:
            data  = json.loads(json_path.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
        except Exception:
            continue
        for idx, task in enumerate(tasks):
            if task.get("name", "").lower() == name.lower():
                return (json_path, data, idx)
    return None


def _task_find_substr(fragment: str) -> "list[tuple]":
    """Return all tasks whose name contains fragment (case-insensitive)."""
    import json
    from utils.workspace_utils import get_schedules_dir

    schedules_dir = get_schedules_dir()
    if not schedules_dir.exists():
        return []

    hits = []
    for json_path in sorted(schedules_dir.glob("*.json")):
        try:
            data  = json.loads(json_path.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
        except Exception:
            continue
        for idx, task in enumerate(tasks):
            if fragment.lower() in task.get("name", "").lower():
                hits.append((json_path, data, idx))
    return hits


def _task_save(json_path: object, data: dict) -> None:
    import json
    json_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------------------------------------

def _cmd_task(arg: str, ctx: SlashCommandContext) -> None:
    """Subcommand dispatcher for /task <sub> [args...]."""
    import json
    import re
    from utils.workspace_utils import get_schedules_dir

    parts = arg.strip().split(None, 1)
    if not parts:
        ctx.output("Usage: /task <enable|disable|add|delete|run> [args]  |  /tasks to list all tasks", "dim")
        return

    sub  = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    # ---- enable / disable ----
    if sub in ("enable", "disable"):
        if not rest:
            ctx.output(f"Usage: /task {sub} <name>", "dim")
            return
        found = _task_find(rest)
        if found is None:
            ctx.output(f"Task '{rest}' not found.", "error")
            return
        json_path, data, idx = found
        data["tasks"][idx]["enabled"] = (sub == "enable")
        _task_save(json_path, data)
        ctx.output(f"Task '{data['tasks'][idx]['name']}' {sub}d.", "success")
        return

    # ---- delete ----
    if sub == "delete":
        if not rest:
            ctx.output("Usage: /task delete <name>", "dim")
            return
        found = _task_find(rest)
        if found is None:
            ctx.output(f"Task '{rest}' not found.", "error")
            return
        json_path, data, idx = found
        removed_name = data["tasks"][idx]["name"]
        data["tasks"].pop(idx)
        if data["tasks"]:
            _task_save(json_path, data)
        else:
            # Remove the file entirely when it's now empty.
            json_path.unlink()
        ctx.output(f"Task '{removed_name}' deleted.", "success")
        return

    # ---- add ----
    if sub == "add":
        # Syntax: /task add <name> <minutes | HH:MM> <prompt text...>
        add_parts = rest.split(None, 2)
        if len(add_parts) < 3:
            ctx.output("Usage: /task add <name> <minutes|HH:MM> <prompt>", "dim")
            ctx.output("  minutes  = interval schedule (e.g. 60)", "dim")
            ctx.output("  HH:MM    = daily schedule at that wall-clock time (e.g. 08:30)", "dim")
            return

        task_name  = add_parts[0]
        sched_arg  = add_parts[1]
        prompt_txt = add_parts[2].strip()

        # Determine schedule type.
        if re.fullmatch(r"\d{1,2}:\d{2}", sched_arg):
            schedule = {"type": "daily", "time": sched_arg}
            sched_str = f"daily @ {sched_arg}"
        else:
            try:
                minutes = int(sched_arg)
            except ValueError:
                ctx.output(f"Invalid schedule '{sched_arg}': use a number of minutes or HH:MM.", "error")
                return
            schedule  = {"type": "interval", "minutes": minutes}
            sched_str = f"every {minutes} min"

        # Check for duplicate name across all files.
        if _task_find(task_name) is not None:
            ctx.output(f"A task named '{task_name}' already exists. Delete it first or choose a different name.", "error")
            return

        schedules_dir = get_schedules_dir()
        schedules_dir.mkdir(parents=True, exist_ok=True)
        json_path = schedules_dir / f"task_{task_name}.json"

        new_data = {
            "tasks": [
                {
                    "name":     task_name,
                    "enabled":  True,
                    "schedule": schedule,
                    "prompts":  [prompt_txt],
                }
            ]
        }
        _task_save(json_path, new_data)
        ctx.output(f"Task '{task_name}' created ({sched_str}).", "success")
        ctx.output(f"  Prompt: {trunc(prompt_txt, 80)}", "dim")
        return

    # ---- run ----
    if sub == "run":
        if not rest:
            ctx.output("Usage: /task run <name>", "dim")
            return
        found = _task_find(rest)
        task_dict = None
        if found is None:
            # Fall back to substring match.
            hits = _task_find_substr(rest)
            if not hits:
                ctx.output(f"Task '{rest}' not found.", "error")
                return
            if len(hits) > 1:
                ctx.output(f"'{rest}' matches {len(hits)} tasks - be more specific:", "error")
                for jp, d, i in hits:
                    ctx.output(f"  {d['tasks'][i]['name']}", "item")
                return
            _, matched_data, matched_idx = hits[0]
            rest      = matched_data["tasks"][matched_idx]["name"]
            task_dict = matched_data["tasks"][matched_idx]
            ctx.output(f"Matched: {rest}", "dim")
        else:
            _, found_data, found_idx = found
            task_dict = found_data["tasks"][found_idx]
        prompts = task_dict.get("prompts", [])
        if not prompts:
            ctx.output(f"Task '{rest}' has no prompts.", "error")
            return
        ctx.output(f"Running task '{rest}' ...", "info")

        def _run_task(
            _rest=rest,
            _prompts=list(prompts),
            _ctx=ctx,
        ) -> None:
            from agent_core.orchestration import ConversationHistory
            from agent_core.orchestration import SessionContext
            from agent_core.orchestration import orchestrate_prompt
            from utils.runtime_logger import SessionLogger
            from utils.runtime_logger import create_log_file_path
            from utils.workspace_utils import get_chatsessions_day_dir
            from utils.workspace_utils import get_logs_dir
            run_log_path = create_log_file_path(log_dir=get_logs_dir())
            task_hist    = ConversationHistory(max_turns=10)
            task_ctx     = SessionContext(
                session_id   = f"task_{_rest}",
                persist_path = get_chatsessions_day_dir() / f"task_{_rest}.json",
            )
            try:
                with SessionLogger(run_log_path) as run_logger:
                    for prompt_text in _prompts:
                        if isinstance(prompt_text, dict):
                            prompt_text = prompt_text.get("prompt", "")
                        if not prompt_text:
                            continue
                        _ctx.output(f"[task] {_rest}: {str(prompt_text)[:80]}", "dim")
                        response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                            user_prompt          = str(prompt_text),
                            config               = _ctx.config,
                            logger               = run_logger,
                            conversation_history = task_hist.as_list() or None,
                            session_context      = task_ctx,
                            quiet                = True,
                        )
                        task_hist.add(str(prompt_text), response)
                        tps_str = f"{tps:.1f}" if tps > 0 else "0"
                        _ctx.output(f"[task] {_rest}: done [{p_tokens:,} tok, {tps_str} tok/s]", "dim")
                        _ctx.output(response, "info")
                _ctx.output(f"Task '{_rest}' completed.", "success")
            except Exception as exc:
                _ctx.output(f"Error running task: {exc}", "error")

        from scheduler.scheduler import task_queue
        queue_name = f"task_run_{rest}"
        if task_queue.enqueue(queue_name, "task_run", _run_task):
            ctx.output(f"Task '{rest}' queued.", "dim")
        else:
            ctx.output(f"Task '{rest}' is already queued or in progress.", "error")
        return

    ctx.output(f"Unknown sub-command '{sub}'. Use: enable, disable, add, delete, run", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_defaults(arg: str, ctx: SlashCommandContext) -> None:
    defaults_path = get_controldata_dir() / "default.json"

    def _load() -> dict:
        try:
            return json.loads(defaults_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    sub = arg.strip().lower()

    if sub == "set":
        existing = _load()
        new_cfg: dict = {
            "model":      ctx.config.resolved_model,
            "ctx":        ctx.config.num_ctx,
            "ollamahost": get_active_host(),
        }
        # Preserve fields we do not own in this command.
        for key in ("agentport", "kiwixurl"):
            if key in existing:
                new_cfg[key] = existing[key]
        try:
            defaults_path.parent.mkdir(parents=True, exist_ok=True)
            defaults_path.write_text(
                json.dumps(new_cfg, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            ctx.output(f"Error saving default.json: {exc}", "error")
            return
        ctx.output(f"Defaults saved to: {defaults_path}", "success")
        for k, v in new_cfg.items():
            ctx.output(f"  {k:<14} {v}", "item")
        return

    if not sub:
        ctx.output(f"Defaults file: {defaults_path}", "info")
        cfg = _load()
        if cfg:
            for k, v in cfg.items():
                ctx.output(f"  {k:<14} {v}", "item")
        else:
            ctx.output("  (file not found or empty)", "dim")
        return

    ctx.output("Usage: /defaults | /defaults set", "dim")


# ----------------------------------------------------------------------------------------------------

def _session_file_scan() -> "list[tuple]":
    """Return (path, data) for every named session JSON file that can be parsed."""
    named_dir = get_chatsessions_named_dir()
    results = []
    if not named_dir.exists():
        return results
    for p in sorted(named_dir.glob("*.json")):
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append((p, data))
            except Exception:
                pass
    return results


def _session_set_name(session_id: str, name: str) -> str:
    """Name a session: move its file to named/session_{slug}.json. Returns the new session_id."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise ValueError(f"Name '{name}' produces an empty slug - use letters or digits.")

    new_session_id = f"session_{slug}"
    named_dir   = get_chatsessions_named_dir()
    target_path = named_dir / f"{new_session_id}.json"
    current_named = named_dir / f"{session_id}.json"
    root_path     = get_chatsessions_dir() / f"{session_id}.json"

    src_path = current_named if current_named.exists() else (root_path if root_path.exists() else None)

    # Refuse if target already belongs to a different session.
    if target_path.exists() and src_path != target_path:
        raise ValueError(f"A session named '{name}' already exists. Choose a different name.")

    data = {}
    if src_path:
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data["name"] = name
    named_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # If the source was a raw (unnamed/root) file, remove it - it has no identity worth keeping.
    # If the source was already a named session in named/, leave it as a frozen checkpoint.
    if src_path and src_path != target_path and src_path.parent != named_dir:
        try:
            src_path.unlink()
        except Exception:
            pass

    return new_session_id


def _cmd_session(arg: str, ctx: SlashCommandContext) -> None:
    sub_parts = arg.strip().split(None, 1)
    sub  = sub_parts[0].lower() if sub_parts else ""
    rest = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if sub == "name":
        if not rest:
            ctx.output("Usage: /session name <alias>", "dim")
            return
        if not ctx.session_id:
            ctx.output("Session naming is not available in this mode.", "error")
            return
        try:
            new_session_id = _session_set_name(ctx.session_id, rest)
        except ValueError as exc:
            ctx.output(str(exc), "error")
            return
        ctx.output(f"Session named '{rest}'.", "success")
        ctx.output(f"  File: named/session_{new_session_id.removeprefix('session_')}.json", "dim")
        if ctx.rename_session:
            ctx.rename_session(new_session_id, rest)
        return

    if sub == "list":
        sessions = _session_file_scan()
        named    = [(p, d) for p, d in sessions if d.get("name")]
        if not named:
            ctx.output("No named sessions found. Use /session name <alias> to name the current session.", "dim")
            return
        ctx.output(f"{len(named)} named session(s):", "info")
        for p, d in named:
            name      = d["name"]
            turns     = len(d.get("turns", []))
            summaries = len(d.get("summaries", []))
            detail    = f"{turns} turn(s)"
            if summaries:
                detail += f" + {summaries} compacted"
            ctx.output(f"  {name:<30}  {detail:<28}  [{p.stem}]", "item")
        return

    if sub == "resume":
        if not rest:
            ctx.output("Usage: /session resume <name>", "dim")
            return
        if not ctx.switch_session:
            ctx.output("Session switching is not available in this mode.", "error")
            return
        sessions = _session_file_scan()
        match    = next(((p, d) for p, d in sessions if d.get("name", "").lower() == rest.lower()), None)
        if not match:
            ctx.output(f"No session named '{rest}' found. Use /session list to see available sessions.", "error")
            return
        path, data  = match
        session_id  = path.stem
        turns       = len(data.get("turns", []))
        summaries   = len(data.get("summaries", []))
        ctx.output(f"Switching to '{rest}' - {turns} turn(s), {summaries} compacted.", "success")
        ctx.switch_session(session_id, rest)
        return

    if sub == "resumecopy":
        parts2 = rest.split(None, 1)
        if len(parts2) < 2:
            ctx.output("Usage: /session resumecopy <oldname> <newname>", "dim")
            return
        src_name, dst_name = parts2[0].strip(), parts2[1].strip()
        if not ctx.switch_session:
            ctx.output("Session switching is not available in this mode.", "error")
            return
        import re as _re
        sessions = _session_file_scan()
        match    = next(((p, d) for p, d in sessions if d.get("name", "").lower() == src_name.lower()), None)
        if not match:
            # Fallback: substring match.
            match = next(((p, d) for p, d in sessions if src_name.lower() in d.get("name", "").lower()), None)
        if not match:
            ctx.output(f"No session named '{src_name}' found. Use /session list to see available sessions.", "error")
            return
        src_path, src_data = match
        slug = _re.sub(r"[^a-z0-9]+", "_", dst_name.lower()).strip("_")
        if not slug:
            ctx.output(f"Name '{dst_name}' produces an empty slug - use letters or digits.", "error")
            return
        new_session_id = f"session_{slug}"
        named_dir      = get_chatsessions_named_dir()
        target_path    = named_dir / f"{new_session_id}.json"
        if target_path.exists():
            ctx.output(f"A session named '{dst_name}' already exists. Choose a different name.", "error")
            return
        copy_data = dict(src_data)
        copy_data["name"] = dst_name
        named_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(copy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        turns     = len(copy_data.get("turns", []))
        summaries = len(copy_data.get("summaries", []))
        ctx.output(f"Copied '{src_data.get('name', src_path.stem)}' -> '{dst_name}' ({turns} turn(s), {summaries} compacted).", "success")
        ctx.output(f"  File: named/{new_session_id}.json", "dim")
        ctx.switch_session(new_session_id, dst_name)
        return

    if sub == "park":
        if not ctx.switch_session:
            ctx.output("Session parking is not available in this mode.", "error")
            return
        import time
        new_id = f"web_{int(time.time() * 1000)}"
        ctx.output("Current session parked - starting fresh chat.", "success")
        ctx.switch_session(new_id, "")
        return

    if sub == "delete":
        if not rest:
            ctx.output("Usage: /session delete <name>  |  /session delete all", "dim")
            return
        sessions = _session_file_scan()
        if rest.lower() == "all":
            if not sessions:
                ctx.output("No named sessions to delete.", "dim")
                return
            deleted_current = False
            count = 0
            for p, d in sessions:
                try:
                    if p.stem == ctx.session_id:
                        deleted_current = True
                    p.unlink()
                    count += 1
                    ctx.output(f"  Deleted '{d.get('name', p.stem)}'.", "item")
                except Exception as exc:
                    ctx.output(f"  Error deleting '{p.name}': {exc}", "error")
            ctx.output(f"{count} session(s) deleted.", "success")
            if deleted_current and ctx.switch_session:
                import time
                new_id = f"web_{int(time.time() * 1000)}"
                ctx.output("Current session was deleted - starting fresh chat.", "info")
                ctx.switch_session(new_id, "")
            return
        # Exact name match (case-insensitive).
        matches = [(p, d) for p, d in sessions if d.get("name", "").lower() == rest.lower()]
        if not matches:
            ctx.output(f"No session with exact name '{rest}' found. Use /session list to check names.", "error")
            return
        deleted_current = False
        for p, d in matches:
            try:
                if p.stem == ctx.session_id:
                    deleted_current = True
                p.unlink()
                ctx.output(f"Deleted session '{d.get('name', p.stem)}'.", "success")
            except Exception as exc:
                ctx.output(f"Error deleting '{p.name}': {exc}", "error")
        if deleted_current and ctx.switch_session:
            import time
            new_id = f"web_{int(time.time() * 1000)}"
            ctx.output("Current session was deleted - starting fresh chat.", "info")
            ctx.switch_session(new_id, "")
        return

    if sub == "info":
        if not ctx.session_id:
            ctx.output("No active session.", "dim")
            return
        named_path = get_chatsessions_named_dir() / f"{ctx.session_id}.json"
        root_path  = get_chatsessions_dir() / f"{ctx.session_id}.json"
        path = named_path if named_path.exists() else root_path
        if not path.exists():
            ctx.output(f"Session '{ctx.session_id}' has no saved file yet.", "dim")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            ctx.output("Could not read session file.", "error")
            return
        name      = data.get("name", "(unnamed)")
        turns     = len(data.get("turns", []))
        summaries = len(data.get("summaries", []))
        ctx.output(f"Current session:", "info")
        ctx.output(f"  Name:       {name}", "item")
        ctx.output(f"  ID:         {ctx.session_id}", "item")
        ctx.output(f"  Turns:      {turns}", "item")
        ctx.output(f"  Summaries:  {summaries}", "item")
        ctx.output(f"  File:       {path}", "item")
        return

    ctx.output("Usage: /session <name|list|resume|resumecopy|park|delete|info>", "dim")
    ctx.output("  /session name <alias>                - name the current session", "item")
    ctx.output("  /session list                        - list all named sessions", "item")
    ctx.output("  /session resume <name>               - switch to a named session", "item")
    ctx.output("  /session resumecopy <old> <new>      - copy a session to a new name and resume it", "item")
    ctx.output("  /session park                        - save current session and start a fresh one", "item")
    ctx.output("  /session delete <name>               - delete a named session (substring match)", "item")
    ctx.output("  /session delete all                  - delete all named sessions", "item")
    ctx.output("  /session info                        - show current session details", "item")


# ====================================================================================================
# MARK: REGISTRY
# ====================================================================================================
_REGISTRY: dict[str, Callable] = {
    "/help":          _cmd_help,
    "/models":        _cmd_models,
    "/model":         _cmd_model,
    "/stoprun":       _cmd_stoprun,
    "/ollamahost":    _cmd_host,
    "/kiwixhost":     _cmd_kiwixhost,
    "/ctx":           _cmd_ctx,
    "/rounds":        _cmd_rounds,
    "/timeout":       _cmd_timeout,
    "/stopmodel":     _cmd_stopmodel,
    "/clearmemory":   _cmd_clearmemory,
    "/newchat":       _cmd_newchat,
    "/reskill":       _cmd_reskills,
    "/sandbox":       _cmd_sandbox,
    "/scratchdump":   _cmd_scratchdump,
    "/deletelogs":    _cmd_deletelogs,
    "/test":          _cmd_test,
    "/testtrend":     _cmd_testtrend,
    "/recall":        _cmd_recall,
    "/tasks":         _cmd_tasks,
    "/task":          _cmd_task,
    "/defaults":      _cmd_defaults,
    "/session":       _cmd_session,
    "/version":       _cmd_version,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":          "List available slash commands",
    "/models":        "List installed Ollama models",
    "/model":         "<name>  Switch active model for all subsequent runs",
    "/stoprun":       "Cancel the active LLM run (after its current round) and clear all pending queued prompts",
    "/ollamahost":    "<hostname|url|local>  Switch active Ollama host (LAN, cloud, or local)",
    "/kiwixhost":     "<url>  Set the Kiwix server URL and save to default.json (takes effect immediately)",
    "/ctx":           "Show context map + window size; sub-cmds: size [<n>], item <n>, compact <n>",
    "/rounds":        "<n>  Set max tool-call rounds per prompt (e.g. /rounds 6)",
    "/timeout":       "<seconds>  Set LLM generation timeout (e.g. /timeout 1800 for heavy analysis)",
    "/stopmodel":     "[name]  Unload a running model from VRAM (defaults to active model)",
    "/clearmemory":   "Delete the memory store file, starting with a blank memory next session",
    "/newchat":       "Clear conversation history and session context, starting a fresh chat",
    "/reskill":       "[min|max]  Rebuild skills catalog and set system prompt guidance mode (default: min)",
    "/sandbox":       "<on|off>  Enable/disable Python code execution sandbox (import whitelist + blocked builtins)",
    "/scratchdump":   "<on|off>  Write scratchpad contents to controldata/scratchpad_dump.txt on every change (default: off)",
    "/deletelogs":    "<days>  Delete log, chatsession, and test_results date-folders older than N days (e.g. /deletelogs 10)",
    "/test":          "<prompts-file|all>  Run test_wrapper on a prompts file (or all files); streams results live",
    "/testtrend":     "[prompts-file]  Show pass-rate trend across all historical test runs (filtered by prompts file if given)",
    "/recall":        "Show a summary of prior skill outputs stored in this session's context",
    "/tasks":         "List all scheduled tasks with status, schedule, and first prompt",
    "/task":          "enable|disable|add|delete|run <name> [schedule] [prompt]  Manage scheduled tasks; /task run <name> executes a task immediately",
    "/defaults":      "Show current default.json settings and file path; /defaults set saves current model/ctx/host to the file",
    "/session":       "name <alias> | list | resume <name> | park | delete <name|all> | info  - manage named session contexts",
    "/version":        "Show framework version, active model, and context size",
}
