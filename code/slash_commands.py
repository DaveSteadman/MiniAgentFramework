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
    lock_input:      Callable[[], None] | None = None   # acquire run lock (blocks until free)
    unlock_input:    Callable[[], None] | None = None   # release run lock


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

    from ollama_client import list_ollama_models, register_session_config, resolve_model_name
    try:
        available = list_ollama_models()
        if not available:
            ctx.output("No models installed in Ollama.", "error")
            return

        resolved = resolve_model_name(arg, available)
        if resolved is None:
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

def _cmd_finalgen(arg: str, ctx: SlashCommandContext) -> None:
    sub = arg.strip().lower()
    if sub == "on":
        ctx.config.skip_final_llm = False
        ctx.output("Final LLM synthesis enabled - skill output will be synthesised by the LLM.", "success")
    elif sub == "off":
        ctx.config.skip_final_llm = True
        ctx.output("Final LLM synthesis disabled - skill output will be returned directly.", "success")
    else:
        state = "off" if ctx.config.skip_final_llm else "on"
        ctx.output(f"Usage: /finalgen <on|off>  |  current: {state}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_newchat(arg: str, ctx: SlashCommandContext) -> None:
    ctx.clear_history()
    ctx.output("Conversation history cleared - starting a new chat.", "success")


# ----------------------------------------------------------------------------------------------------

def _cmd_clearmemory(arg: str, ctx: SlashCommandContext) -> None:
    from pathlib import Path
    store_path = Path(__file__).resolve().parent / "skills" / "Memory" / "memory_store.json"
    legacy_path = Path(__file__).resolve().parent / "skills" / "Memory" / "memory_store.txt"

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
    from skills_catalog_builder import (
        find_skill_files, summarize_skill, normalize_summary,
        render_summary_document, DEFAULT_SKILLS_ROOT, DEFAULT_OUTPUT_FILE,
        load_skills_payload,
    )

    skills_root = DEFAULT_SKILLS_ROOT
    output_path = DEFAULT_OUTPUT_FILE

    ctx.output("Rebuilding skills catalog (local extraction, no LLM)…", "dim")
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
            f"Skills catalog rebuilt: {len(summaries)} skill(s) registered.",
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
            f"Usage: /host <hostname|url|local> [api-key]  |  current: {get_active_host()}",
            "dim",
        )
        return

    parts   = arg.split(None, 1)
    raw     = parts[0].strip()
    api_key = parts[1].strip() if len(parts) > 1 else None

    old_host = get_active_host()

    try:
        configure_host(raw, api_key)
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

def _cmd_test(arg: str, ctx: SlashCommandContext) -> None:
    import re
    import subprocess
    import sys
    from pathlib import Path
    from ollama_client import get_active_api_key, get_active_host

    test_prompts_dir = Path(__file__).resolve().parent.parent / "controldata" / "test_prompts"

    if not arg:
        ctx.output(
            "Usage: /test <prompts-file>  (filename from controldata/test_prompts/ or full path)",
            "dim",
        )
        if test_prompts_dir.exists():
            files = sorted(test_prompts_dir.glob("*.json"))
            if files:
                ctx.output("Available files:", "info")
                for f in files:
                    ctx.output(f"  {f.name}", "item")
        return

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

    wrapper = Path(__file__).resolve().parent.parent / "testcode" / "test_wrapper.py"
    cmd = [
        sys.executable, str(wrapper),
        "--prompts-file", str(candidate),
        "--model", ctx.config.resolved_model,
    ]
    active_host = get_active_host()
    if "localhost" not in active_host and "127.0.0.1" not in active_host:
        cmd += ["--ollama-host", active_host]
    active_key = get_active_api_key()
    if active_key:
        cmd += ["--ollama-api-key", active_key]

    ctx.output(f"Running test suite: {candidate.name} …", "info")
    if ctx.lock_input:
        ctx.lock_input()
    _summary_re = re.compile(r"^\[TEST_SUMMARY\] passed=(\d+) total=(\d+)$")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        test_passed = test_total = None
        for line in proc.stdout:
            stripped = line.rstrip()
            m = _summary_re.match(stripped)
            if m:
                test_passed = int(m.group(1))
                test_total  = int(m.group(2))
            else:
                ctx.output(stripped, "dim")
        proc.wait()
        if test_passed is not None:
            level = "success" if test_passed == test_total else "error"
            ctx.output(f"[Test: {candidate.name}  Passed {test_passed}/{test_total}]", level)
        elif proc.returncode == 0:
            ctx.output("Test suite completed.", "success")
        else:
            ctx.output(f"Test suite exited with code {proc.returncode}.", "error")
    except Exception as exc:
        ctx.output(f"Error running test wrapper: {exc}", "error")
    finally:
        if ctx.unlock_input:
            ctx.unlock_input()


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

    if deleted:
        ctx.output(f"Deleted {len(deleted)} date-folder(s): {', '.join(deleted)}", "success")
    else:
        ctx.output(f"No date-folders older than {days} day(s) found.", "dim")
    for err in errors:
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
        from ollama_client import get_active_api_key, get_active_host
        if not rest:
            ctx.output("Usage: /task run <name>", "dim")
            return
        if _task_find(rest) is None:
            ctx.output(f"Task '{rest}' not found.", "error")
            return
        main_py = Path(__file__).resolve().parent / "main.py"
        cmd = [
            sys.executable, "-X", "utf8", str(main_py),
            "--scheduled-item", rest,
            "--model", ctx.config.resolved_model,
        ]
        active_host = get_active_host()
        if "localhost" not in active_host and "127.0.0.1" not in active_host:
            cmd += ["--ollama-host", active_host]
        active_key = get_active_api_key()
        if active_key:
            cmd += ["--ollama-api-key", active_key]
        ctx.output(f"Running task '{rest}' …", "info")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                ctx.output(line.rstrip(), "dim")
            proc.wait()
            if proc.returncode == 0:
                ctx.output(f"Task '{rest}' completed.", "success")
            else:
                ctx.output(f"Task '{rest}' exited with code {proc.returncode}.", "error")
        except Exception as exc:
            ctx.output(f"Error running task: {exc}", "error")
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
    "/finalgen":      _cmd_finalgen,
    "/sandbox":       _cmd_sandbox,
    "/scratchdump":   _cmd_scratchdump,
    "/deletelogs":    _cmd_deletelogs,
    "/test":          _cmd_test,
    "/recall":        _cmd_recall,
    "/tasks":         _cmd_tasks,
    "/task":          _cmd_task,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":          "List available slash commands",
    "/exit":          "Exit dashboard mode",
    "/models":        "List installed Ollama models",
    "/model":         "<name>  Switch active model for all subsequent runs",
    "/host":          "<hostname|url|local> [api-key]  Switch active Ollama host (LAN, cloud, or local)",
    "/ctx":           "Show context map + window size; sub-cmds: size [<n>], item <n>, compact <n>",
    "/rounds":        "<n>  Set max tool-call rounds per prompt (e.g. /rounds 6)",
    "/timeout":       "<seconds>  Set LLM generation timeout (e.g. /timeout 1800 for heavy analysis)",
    "/stopmodel":     "[name]  Unload a running model from VRAM (defaults to active model)",
    "/clearmemory":   "Delete the memory store file, starting with a blank memory next session",
    "/newchat":       "Clear conversation history and session context, starting a fresh chat",
    "/reskill":       "Rebuild the skills catalog from skill.md files and hot-reload into session",
    "/finalgen":      "<on|off>  Enable/disable final LLM synthesis of skill output (default: on)",
    "/sandbox":       "<on|off>  Enable/disable Python code execution sandbox (import whitelist + blocked builtins)",
    "/scratchdump":   "<on|off>  Write scratchpad contents to controldata/scratchpad_dump.txt on every change (default: off)",
    "/deletelogs":    "<days>  Delete log and chatsession date-folders older than N days (e.g. /deletelogs 10)",
    "/test":          "<prompts-file>  Run test_wrapper on a prompts file; streams results live",
    "/recall":        "Show a summary of prior skill outputs stored in this session's context",
    "/tasks":         "List all scheduled tasks with status, schedule, and first prompt",
    "/task":          "enable|disable|add|delete|run <name> [schedule] [prompt]  Manage scheduled tasks; /task run <name> executes a task immediately",
}
