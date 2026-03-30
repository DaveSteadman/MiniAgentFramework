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
#   - main.py           -- creates contexts and calls handle() in each input mode
#   - ollama_client.py  -- list_ollama_models, resolve_model_name used by /model commands
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from dataclasses import dataclass
from typing import Callable

from workspace_utils import trunc


# ====================================================================================================
# MARK: CONTEXT
# ====================================================================================================
@dataclass
class SlashCommandContext:
    """All mutable state and I/O wiring needed by slash command handlers."""
    config:          object                        # OrchestratorConfig; .resolved_model is writable
    output:          Callable[[str, str], None]    # (text, level) -> None
    clear_history:   Callable[[], None]            # resets conversation history + session context
    request_exit:    Callable[[], None] | None = None   # optional: signals the host to shut down
    session_context: object | None = None               # SessionContext; None in non-interactive modes


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
# Handler functions import their heavy dependencies inside the function body rather than at module
# level.  This is intentional: it avoids circular-import risk at startup and keeps the import cost
# near-zero when only a subset of commands are ever invoked in a given session.
# ====================================================================================================




def _cmd_help(arg: str, ctx: SlashCommandContext) -> None:
    ctx.output("Available slash commands:", "info")
    for name, description in sorted(_DESCRIPTIONS.items()):
        ctx.output(f"  {name:<16} {description}", "item")


# ----------------------------------------------------------------------------------------------------

def _cmd_exit(arg: str, ctx: SlashCommandContext) -> None:
    if ctx.request_exit is None:
        ctx.output("/exit is not available in this mode.", "error")
        return
    ctx.output("Exiting...", "dim")
    ctx.request_exit()


# ----------------------------------------------------------------------------------------------------

def _cmd_models(arg: str, ctx: SlashCommandContext) -> None:
    from ollama_client import list_ollama_models
    try:
        available = list_ollama_models()
        ctx.output(f"{len(available)} model(s) installed:", "info")
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

    from ollama_client import (
        is_explicit_model_name,
        list_ollama_models,
        register_session_config,
        resolve_model_name,
    )
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
        from orchestration import get_last_context_map
        from orchestration import get_last_messages
        return get_last_context_map(), get_last_messages()

    def _show_map(context_map):
        from orchestration import _format_context_map
        ctx.output(_format_context_map(context_map, ctx.config.num_ctx), "item")

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
        from ollama_client import register_session_config
        register_session_config(ctx.config.resolved_model, value)
        ctx.output(f"Context window size changed: {old:,} \u2192 {value:,}", "success")
        return

    # /ctx item <num> - show raw message content at map index N.
    if sub == "item":
        if not rest:
            ctx.output("Usage: /ctx item <index>", "dim")
            return
        context_map, messages = _get_map_and_messages()
        if not context_map:
            ctx.output("No run context available - send a prompt first.", "error")
            return
        try:
            idx = int(rest)
        except ValueError:
            ctx.output(f"Invalid index '{rest}' - must be an integer.", "error")
            return
        if idx < 0 or idx >= len(context_map):
            ctx.output(f"Index {idx} out of range (0 - {len(context_map) - 1}).", "error")
            return
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
        context_map, messages = _get_map_and_messages()
        if not context_map:
            ctx.output("No run context available - send a prompt first.", "error")
            return
        try:
            idx = int(rest)
        except ValueError:
            ctx.output(f"Invalid index '{rest}' - must be an integer.", "error")
            return
        if idx < 0 or idx >= len(context_map):
            ctx.output(f"Index {idx} out of range (0 - {len(context_map) - 1}).", "error")
            return
        entry = context_map[idx]
        if entry.get("msg_idx") is None:
            ctx.output(
                f"Entry {idx} ({entry.get('role')} / {entry.get('label')}) has no associated message - cannot compact.",
                "error",
            )
            return
        ctx.output("Before:", "dim")
        _show_map(context_map)
        from orchestration import compact_context
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
    from ollama_client import get_llm_timeout, set_llm_timeout
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
    from ollama_client import get_ollama_ps_rows, list_ollama_models, resolve_model_name, stop_model

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
    from scratchpad import get_dump_enabled, set_dump_enabled, flush_now
    from workspace_utils import get_controldata_dir

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
    from skills.Memory.memory_skill import MEMORY_STORE_PATH
    from skills.Memory.memory_skill import MEMORY_STORE_LEGACY_PATH
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
    from pathlib import Path
    from orchestration import get_skill_guidance_enabled, set_skill_guidance_enabled
    from skills_catalog_builder import (
        find_skill_files, summarize_skill, normalize_summary,
        render_summary_document, DEFAULT_SKILLS_ROOT, DEFAULT_OUTPUT_FILE,
        load_skills_payload,
    )

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

    skills_root = DEFAULT_SKILLS_ROOT
    output_path = DEFAULT_OUTPUT_FILE

    current_mode = "max" if get_skill_guidance_enabled() else "min"
    ctx.output(f"Rebuilding skills catalog (local extraction, no LLM) - mode: {current_mode}...", "dim")
    try:
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

def _cmd_host(arg: str, ctx: SlashCommandContext) -> None:
    from ollama_client import configure_host, get_active_host, list_ollama_models

    if not arg:
        ctx.output(
            f"Usage: /host <hostname|url|local>  |  current: {get_active_host()}",
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
        cmd += ["--ollama-host", active_host]
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
        for line in proc.stdout:
            stripped = line.rstrip()
            m = _summary_re.match(stripped)
            if m:
                test_passed = int(m.group(1))
                test_total  = int(m.group(2))
            else:
                metrics_match = _metrics_re.match(stripped)
                if metrics_match:
                    prompt_tokens_total += int(metrics_match.group(2))
                    turn_tps = float(metrics_match.group(3))
                    if turn_tps > 0:
                        tps_sum     += turn_tps
                        tps_samples += 1
                ctx.output(stripped, "dim")
        proc.wait()
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
    # Runs test_regressions.py and test_cot_preamble.py (no LLM, completes in seconds),
    # then test_analyzer.py on the CSV to produce _analysis.csv and _gaps.txt alongside it.
    ctx.output("--- Post-test checks ---", "dim")
    for script_name in ("test_regressions.py", "test_cot_preamble.py"):
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
    from pathlib import Path
    from ollama_client import get_active_host
    from scheduler import task_queue
    from workspace_utils import get_test_results_dir

    test_prompts_dir = Path(__file__).resolve().parent.parent / "controldata" / "test_prompts"
    wrapper          = Path(__file__).resolve().parent.parent / "testcode" / "test_wrapper.py"

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

        if task_queue.enqueue("test_all", "test", _run_all):
            ctx.output("Test run queued.", "dim")
        else:
            ctx.output("A test run is already queued or in progress.", "error")
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

    queue_name = f"test_{candidate.stem}"
    if task_queue.enqueue(queue_name, "test", _run_single):
        ctx.output(f"Test queued: {candidate.name}", "dim")
    else:
        ctx.output(f"Test '{candidate.name}' is already queued or in progress.", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_version(arg: str, ctx: SlashCommandContext) -> None:
    from version import __version__
    ctx.output(f"MiniAgentFramework {__version__}", "info")
    ctx.output(f"  model:   {ctx.config.resolved_model}", "item")
    ctx.output(f"  num_ctx: {ctx.config.num_ctx:,}", "item")


# ----------------------------------------------------------------------------------------------------
def _cmd_sandbox(arg: str, ctx: SlashCommandContext) -> None:
    import sys
    from pathlib import Path
    from workspace_utils import get_workspace_root

    # Locate the canonical module name used by skill_executor so we toggle the same
    # module instance that runs tool calls, rather than a freshly imported duplicate.
    skill_path  = (get_workspace_root() / "code/skills/CodeExecute/code_execute_skill.py").resolve()
    canon_name  = f"skill_module_code_execute_skill_{abs(hash(str(skill_path)))}"
    skill_mod   = sys.modules.get(canon_name)

    # Fall back to a direct import when skill_executor hasn't loaded it yet (e.g. first use
    # before any tool call ran).  After this import the module IS the authoritative copy,
    # but skill_executor will pick up the same object via sys.modules on its first load.
    if skill_mod is None:
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location(canon_name, skill_path)
            if spec is None or spec.loader is None:
                raise ImportError("Cannot load spec")
            skill_mod = _ilu.module_from_spec(spec)
            sys.modules[canon_name] = skill_mod
            spec.loader.exec_module(skill_mod)
        except Exception:
            ctx.output("CodeExecute skill not available.", "error")
            return

    get_sandbox_enabled = getattr(skill_mod, "get_sandbox_enabled", None)
    set_sandbox_enabled = getattr(skill_mod, "set_sandbox_enabled", None)
    if not callable(get_sandbox_enabled) or not callable(set_sandbox_enabled):
        ctx.output("CodeExecute skill does not expose sandbox control functions.", "error")
        return

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
    from workspace_utils import get_chatsessions_dir
    from workspace_utils import get_logs_dir

    if not arg.strip():
        ctx.output("Usage: /deletelogs <days>  |  delete log and chatsession date-folders older than N days", "dim")
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

    for base_dir in (get_logs_dir(), get_chatsessions_dir()):
        if not base_dir.exists():
            continue
        for folder in sorted(base_dir.iterdir()):
            if not folder.is_dir() or not date_re.match(folder.name):
                continue
            try:
                folder_date = date.fromisoformat(folder.name)
            except ValueError:
                continue
            if folder_date < cutoff:
                try:
                    shutil.rmtree(folder)
                    deleted.append(f"{base_dir.name}/{folder.name}")
                except Exception as exc:
                    errors.append(f"{base_dir.name}/{folder.name}: {exc}")

    stray_deleted = []
    stray_errors  = []

    for base_dir in (get_logs_dir(), get_chatsessions_dir()):
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
        ctx.output(f"Deleted {len(deleted)} date-folder(s): {', '.join(deleted)}", "success")
    else:
        ctx.output(f"No date-folders older than {days} day(s) found.", "dim")
    if stray_deleted:
        ctx.output(f"Deleted {len(stray_deleted)} stray file(s): {', '.join(stray_deleted)}", "success")
    for err in errors + stray_errors:
        ctx.output(f"Error deleting {err}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_tasks(arg: str, ctx: SlashCommandContext) -> None:
    """List all scheduled tasks from every JSON file in the schedules directory."""
    import json
    from workspace_utils import get_schedules_dir

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
    from workspace_utils import get_schedules_dir

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
    from workspace_utils import get_schedules_dir

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
    from workspace_utils import get_schedules_dir

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
        import subprocess
        import sys
        from pathlib import Path
        from ollama_client import get_active_host
        if not rest:
            ctx.output("Usage: /task run <name>", "dim")
            return
        found = _task_find(rest)
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
            rest = matched_data["tasks"][matched_idx]["name"]
            ctx.output(f"Matched: {rest}", "dim")
        main_py = Path(__file__).resolve().parent / "main.py"
        cmd = [
            sys.executable, "-X", "utf8", str(main_py),
            "--scheduled-item", rest,
            "--model", ctx.config.resolved_model,
        ]
        active_host = get_active_host()
        if "localhost" not in active_host and "127.0.0.1" not in active_host:
            cmd += ["--ollama-host", active_host]
        ctx.output(f"Running task '{rest}' ...", "info")

        def _run_task(
            _rest=rest,
            _cmd=list(cmd),
            _ctx=ctx,
        ) -> None:
            try:
                proc = subprocess.Popen(
                    _cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                for line in proc.stdout:
                    _ctx.output(line.rstrip(), "dim")
                proc.wait()
                if proc.returncode == 0:
                    _ctx.output(f"Task '{_rest}' completed.", "success")
                else:
                    _ctx.output(f"Task '{_rest}' exited with code {proc.returncode}.", "error")
            except Exception as exc:
                _ctx.output(f"Error running task: {exc}", "error")

        from scheduler import task_queue
        queue_name = f"task_run_{rest}"
        if task_queue.enqueue(queue_name, "task_run", _run_task):
            ctx.output(f"Task '{rest}' queued.", "dim")
        else:
            ctx.output(f"Task '{rest}' is already queued or in progress.", "error")
        return

    ctx.output(f"Unknown sub-command '{sub}'. Use: enable, disable, add, delete, run", "error")


# ====================================================================================================
# MARK: REGISTRY
# ====================================================================================================
_REGISTRY: dict[str, Callable] = {
    "/help":          _cmd_help,
    "/exit":          _cmd_exit,
    "/models":        _cmd_models,
    "/model":         _cmd_model,
    "/host":          _cmd_host,
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
    "/recall":        _cmd_recall,
    "/tasks":         _cmd_tasks,
    "/task":          _cmd_task,
    "/version":        _cmd_version,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":          "List available slash commands",
    "/exit":          "Exit dashboard mode",
    "/models":        "List installed Ollama models",
    "/model":         "<name>  Switch active model for all subsequent runs",
    "/host":          "<hostname|url|local>  Switch active Ollama host (LAN, cloud, or local)",
    "/ctx":           "Show context map + window size; sub-cmds: size [<n>], item <n>, compact <n>",
    "/rounds":        "<n>  Set max tool-call rounds per prompt (e.g. /rounds 6)",
    "/timeout":       "<seconds>  Set LLM generation timeout (e.g. /timeout 1800 for heavy analysis)",
    "/stopmodel":     "[name]  Unload a running model from VRAM (defaults to active model)",
    "/clearmemory":   "Delete the memory store file, starting with a blank memory next session",
    "/newchat":       "Clear conversation history and session context, starting a fresh chat",
    "/reskill":       "[min|max]  Rebuild skills catalog and set system prompt guidance mode (default: min)",
    "/sandbox":       "<on|off>  Enable/disable Python code execution sandbox (import whitelist + blocked builtins)",
    "/scratchdump":   "<on|off>  Write scratchpad contents to controldata/scratchpad_dump.txt on every change (default: off)",
    "/deletelogs":    "<days>  Delete log and chatsession date-folders older than N days (e.g. /deletelogs 10)",
    "/test":          "<prompts-file|all>  Run test_wrapper on a prompts file (or all files); streams results live",
    "/recall":        "Show a summary of prior skill outputs stored in this session's context",
    "/tasks":         "List all scheduled tasks with status, schedule, and first prompt",
    "/task":          "enable|disable|add|delete|run <name> [schedule] [prompt]  Manage scheduled tasks; /task run <name> executes a task immediately",
    "/version":        "Show framework version, active model, and context size",
}
