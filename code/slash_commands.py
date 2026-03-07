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
#       clear_history = my_clear_fn,       # () -> None  — called when history must be reset
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
        ctx.output(f"Invalid value '{arg}' — must be an integer (e.g. /ctx 32768).", "error")
        return
    if value < 512:
        ctx.output("Context size must be at least 512 tokens.", "error")
        return
    old = ctx.config.num_ctx
    ctx.config.num_ctx = value
    ctx.output(f"Context size changed: {old:,} \u2192 {value:,}", "success")


# ====================================================================================================
# MARK: REGISTRY
# ====================================================================================================
_REGISTRY: dict[str, Callable] = {
    "/help":   _cmd_help,
    "/models": _cmd_models,
    "/model":  _cmd_model,
    "/ctx":    _cmd_ctx,
}

_DESCRIPTIONS: dict[str, str] = {
    "/help":   "List available slash commands",
    "/models": "List installed Ollama models",
    "/model":  "<name>  Switch active model for all subsequent runs",
    "/ctx":    "<tokens>  Set context window size (e.g. /ctx 32768)",
}
