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

# Well-known Ollama host aliases resolved by the /host command.
_HOST_ALIASES: dict[str, str] = {
    "local":     "http://localhost:11434",
    "localhost":  "http://localhost:11434",
}


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

    from ollama_client import list_ollama_models, resolve_model_name
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
        ctx.clear_history()
        ctx.output(f"Model switched: {old} \u2192 {resolved}", "success")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        ctx.output(f"Error: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_ctx(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(
            f"Usage: /ctx <tokens>  |  current: {ctx.config.num_ctx:,}",
            "dim",
        )
        return
    try:
        value = int(arg.strip().replace(",", "").replace("_", ""))
    except ValueError:
        ctx.output(f"Invalid value '{arg}' - must be an integer (e.g. /ctx 32768).", "error")
        return
    if value < 512:
        ctx.output("Context size must be at least 512 tokens.", "error")
        return
    old = ctx.config.num_ctx
    ctx.config.num_ctx = value
    ctx.output(f"Context size changed: {old:,} \u2192 {value:,}", "success")


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
    )
    from planner_engine import load_skills_payload

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
    for t in sc._turns:
        ctx.output(f"  Turn {t['turn']}: {t['user_prompt'][:80]}", "item")
        for o in t["skill_outputs"]:
            skill   = o.get("skill", "?")
            summary = o.get("summary", "")
            url     = o.get("url", "")
            extra   = f"  url: {url}" if url else ""
            ctx.output(f"    [{skill}] {summary}{extra}", "dim")
            for r in o.get("results", []):
                ctx.output(f"      · {r.get('url', '')}  {r.get('title', '')[:60]}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_host(arg: str, ctx: SlashCommandContext) -> None:
    from ollama_client import configure_host, get_active_host, list_ollama_models

    if not arg:
        ctx.output(
            f"Usage: /host <hostname|url|local> [api-key]  |  current: {get_active_host()}",
            "dim",
        )
        return

    parts     = arg.split(None, 1)
    raw       = parts[0].strip()
    api_key   = parts[1].strip() if len(parts) > 1 else None

    # Resolve well-known aliases first, then treat bare hostnames / IPs
    # (anything without a scheme) as Ollama servers on the default port.
    url = _HOST_ALIASES.get(raw.lower(), raw)
    if "://" not in url:
        url = f"http://{url}:11434"

    old_host = get_active_host()

    try:
        configure_host(url, api_key)
        models = list_ollama_models()
        ctx.clear_history()
        ctx.output(f"Host switched: {old_host} \u2192 {url}", "success")
        if models:
            ctx.output(f"  {len(models)} model(s): {', '.join(models)}", "item")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        configure_host(old_host)
        ctx.output(f"Cannot reach '{url}': {exc}", "error")
        ctx.output(f"Still using: {old_host}", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_test(arg: str, ctx: SlashCommandContext) -> None:
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
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        for line in proc.stdout:
            ctx.output(line.rstrip(), "dim")
        proc.wait()
        if proc.returncode == 0:
            ctx.output("Test suite completed.", "success")
        else:
            ctx.output(f"Test suite exited with code {proc.returncode}.", "error")
    except Exception as exc:
        ctx.output(f"Error running test wrapper: {exc}", "error")


# ----------------------------------------------------------------------------------------------------

def _cmd_sandbox(arg: str, ctx: SlashCommandContext) -> None:
    try:
        from skills.CodeExecute.code_execute_skill import get_sandbox_enabled, set_sandbox_enabled
    except ImportError:
        ctx.output("CodeExecute skill not available.", "error")
        return

    sub = arg.strip().lower()
    if sub == "on":
        set_sandbox_enabled(True)
        ctx.output("Python sandbox enabled — imports restricted to the safe whitelist.", "success")
    elif sub == "off":
        set_sandbox_enabled(False)
        ctx.output("Python sandbox disabled — code snippets run with full Python access.", "success")
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
    from workspace_utils import get_logs_dir

    if not arg.strip():
        ctx.output("Usage: /deletelogs <days>  |  delete log date-folders older than N days", "dim")
        return

    try:
        days = int(arg.strip())
    except ValueError:
        ctx.output(f"Invalid value '{arg}' - must be an integer number of days.", "error")
        return

    if days < 1:
        ctx.output("Days must be at least 1.", "error")
        return

    log_dir    = get_logs_dir()
    cutoff     = date.today() - timedelta(days=days)
    date_re    = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    deleted    = []
    errors     = []

    for folder in sorted(log_dir.iterdir()):
        if not folder.is_dir() or not date_re.match(folder.name):
            continue
        try:
            folder_date = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            try:
                shutil.rmtree(folder)
                deleted.append(folder.name)
            except Exception as exc:
                errors.append(f"{folder.name}: {exc}")

    if deleted:
        ctx.output(f"Deleted {len(deleted)} log folder(s): {', '.join(deleted)}", "success")
    else:
        ctx.output(f"No log date-folders older than {days} day(s) found.", "dim")
    for err in errors:
        ctx.output(f"Error deleting {err}", "error")


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
    "/timeout":       _cmd_timeout,
    "/stopmodel":     _cmd_stopmodel,
    "/clearmemory":   _cmd_clearmemory,
    "/reskill":       _cmd_reskills,
    "/finalgen":      _cmd_finalgen,
    "/sandbox":       _cmd_sandbox,
    "/deletelogs":    _cmd_deletelogs,
    "/test":          _cmd_test,
    "/recall":        _cmd_recall,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":          "List available slash commands",
    "/exit":          "Exit dashboard mode",
    "/models":        "List installed Ollama models",
    "/model":         "<name>  Switch active model for all subsequent runs",
    "/host":          "<hostname|url|local> [api-key]  Switch active Ollama host (LAN, cloud, or local)",
    "/ctx":           "<tokens>  Set context window size (e.g. /ctx 32768)",
    "/timeout":       "<seconds>  Set LLM generation timeout (e.g. /timeout 1800 for heavy analysis)",
    "/stopmodel":     "[name]  Unload a running model from VRAM (defaults to active model)",
    "/clearmemory":   "Delete the memory store file, starting with a blank memory next session",
    "/reskill":       "Rebuild the skills catalog from skill.md files and hot-reload into session",
    "/finalgen":      "<on|off>  Enable/disable final LLM synthesis of skill output (default: on)",
    "/sandbox":       "<on|off>  Enable/disable Python code execution sandbox (import whitelist + blocked builtins)",
    "/deletelogs":    "<days>  Delete log date-folders older than N days (e.g. /deletelogs 10)",
    "/test":          "<prompts-file>  Run test_wrapper on a prompts file; streams results live",
    "/recall":        "Show a summary of prior skill outputs stored in this session's context",
}
