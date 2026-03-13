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
    config:        object                        # OrchestratorConfig; .resolved_model is writable
    output:        Callable[[str, str], None]    # (text, level) -> None
    clear_history: Callable[[], None]            # resets conversation history
    request_exit:  Callable[[], None] | None = None  # optional: signals the host to shut down


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

def _cmd_skip_final(arg: str, ctx: SlashCommandContext) -> None:
    ctx.config.skip_final_llm = True
    ctx.output("Final LLM synthesis disabled - skill output will be returned directly.", "success")
    ctx.output("Use /run-final to re-enable.", "dim")


# ----------------------------------------------------------------------------------------------------

def _cmd_run_final(arg: str, ctx: SlashCommandContext) -> None:
    ctx.config.skip_final_llm = False
    ctx.output("Final LLM synthesis re-enabled.", "success")


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


# ====================================================================================================
# MARK: REGISTRY
# ====================================================================================================
_REGISTRY: dict[str, Callable] = {
    "/help":          _cmd_help,
    "/exit":          _cmd_exit,
    "/models":        _cmd_models,
    "/model":         _cmd_model,
    "/ctx":           _cmd_ctx,
    "/timeout":       _cmd_timeout,
    "/stopmodel":     _cmd_stopmodel,
    "/clearmemory":   _cmd_clearmemory,
    "/reskill":       _cmd_reskills,
    "/skip-final":    _cmd_skip_final,
    "/run-final":     _cmd_run_final,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":          "List available slash commands",
    "/exit":          "Exit dashboard mode",
    "/models":        "List installed Ollama models",
    "/model":         "<name>  Switch active model for all subsequent runs",
    "/ctx":           "<tokens>  Set context window size (e.g. /ctx 32768)",
    "/timeout":       "<seconds>  Set LLM generation timeout (e.g. /timeout 1800 for heavy analysis)",
    "/stopmodel":     "[name]  Unload a running model from VRAM (defaults to active model)",
    "/clearmemory":   "Delete the memory store file, starting with a blank memory next session",
    "/reskill":       "Rebuild the skills catalog from skill.md files and hot-reload into session",
    "/skip-final":    "Skip the final LLM synthesis call; return skill output directly",
    "/run-final":     "Re-enable the final LLM synthesis call (default state)",
}
