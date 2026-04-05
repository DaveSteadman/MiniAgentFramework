import json
import urllib.request
from typing import Callable

from agent_core.ollama_client import configure_host
from agent_core.ollama_client import get_active_host
from agent_core.ollama_client import get_ollama_ps_rows
from agent_core.ollama_client import is_explicit_model_name
from agent_core.ollama_client import list_ollama_models
from agent_core.ollama_client import register_session_config
from agent_core.ollama_client import resolve_model_name
from agent_core.ollama_client import stop_model
from input_layer.slash_command_context import SlashCommandContext
from utils.workspace_utils import get_bootstrap_defaults_file


def _cmd_models(arg: str, ctx: SlashCommandContext) -> None:
    try:
        available = list_ollama_models()
        host = get_active_host()
        ctx.output(f"{len(available)} model(s) installed on: {host}", "info")
        for model_name in available:
            marker = "\u25ba" if model_name == ctx.config.resolved_model else " "
            ctx.output(f"  {marker} {model_name}", "item")
    except Exception as exc:
        ctx.output(f"Error listing models: {exc}", "error")


def _cmd_model(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(f"Usage: /model <name>  |  current: {ctx.config.resolved_model}", "dim")
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
                ctx.output(f"Model '{arg}' not found.  Available: {', '.join(available)}", "error")
                return

        old = ctx.config.resolved_model
        ctx.config.resolved_model = resolved
        register_session_config(resolved, ctx.config.num_ctx)
        ctx.clear_history()
        ctx.output(f"Model switched: {old} \u2192 {resolved}", "success")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        ctx.output(f"Error: {exc}", "error")


def _cmd_stopmodel(arg: str, ctx: SlashCommandContext) -> None:
    target_name = arg.strip() if arg.strip() else ctx.config.resolved_model
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


def _cmd_kiwixhost(arg: str, ctx: SlashCommandContext) -> None:
    defaults_path = get_bootstrap_defaults_file()

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
        defaults_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        ctx.output(f"Error saving default.json: {exc}", "error")
        return

    ctx.output(f"Kiwix host updated: {old} -> {raw}", "success")
    ctx.output("Takes effect immediately - no restart required.", "dim")


def _cmd_ollama_host(arg: str, ctx: SlashCommandContext) -> None:
    if not arg:
        ctx.output(f"Usage: /ollamahost <hostname|url|local>  |  current: {get_active_host()}", "dim")
        return

    raw = arg.strip()
    old_host = get_active_host()

    try:
        configure_host(raw)
        new_host = get_active_host()
        models = list_ollama_models()
        ctx.clear_history()
        ctx.output(f"Host switched: {old_host} \u2192 {new_host}", "success")
        if models:
            ctx.output(f"  {len(models)} model(s): {', '.join(models)}", "item")
        ctx.output("(conversation history cleared)", "dim")
    except Exception as exc:
        configure_host(old_host)
        ctx.output(f"Cannot reach '{raw}': {exc}", "error")
        ctx.output(f"Still using: {old_host}", "dim")


def register_model_slash_commands(registry: dict[str, Callable], descriptions: dict[str, str]) -> None:
    registry.update(
        {
            "/models": _cmd_models,
            "/model": _cmd_model,
            "/stopmodel": _cmd_stopmodel,
            "/kiwixhost": _cmd_kiwixhost,
            "/ollamahost": _cmd_ollama_host,
        }
    )
    descriptions.update(
        {
            "/models": "List installed Ollama models",
            "/model": "<name>  Switch active model for all subsequent runs",
            "/stopmodel": "[name]  Unload a running model from VRAM (defaults to active model)",
            "/kiwixhost": "<url>  Set the Kiwix server URL and save to default.json (takes effect immediately)",
            "/ollamahost": "<hostname|url|local>  Switch active Ollama host (LAN, cloud, or local)",
        }
    )
