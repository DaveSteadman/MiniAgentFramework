# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# CLI entrypoint for MiniAgentFramework.
#
# Default mode: starts the FastAPI server with the web UI.
# Test mode (--chat-sequence-file): runs a pre-defined prompt sequence and exits.
#
# Core orchestration pipeline lives in orchestration.py.
# API/web mode lives in modes/api_mode.py.
#
# Related modules:
#   - orchestration.py          -- OrchestratorConfig, ConversationHistory, orchestrate_prompt
#   - modes/api_mode.py         -- run_api_mode (FastAPI + uvicorn + scheduler)
#   - ollama_client.py          -- Ollama server management and LLM calls
#   - skills_catalog_builder.py -- load_skills_payload, tool definitions
#   - runtime_logger.py         -- SessionLogger, create_log_file_path
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import os
from pathlib import Path

import ollama_client
from modes.api_mode import run_api_mode
from ollama_client import format_running_model_report
from ollama_client import get_llm_timeout
from ollama_client import register_llm_call_logger
from orchestration import ConversationHistory
from orchestration import OrchestratorConfig
from orchestration import SessionContext
from orchestration import orchestrate_prompt
from orchestration import resolve_execution_model
from skills_catalog_builder import load_skills_payload
from runtime_logger import create_log_file_path
from runtime_logger import SessionLogger
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from workspace_utils import get_chatsessions_day_dir
from workspace_utils import get_logs_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_NUM_CTX      = 131072
MAX_ITERATIONS       = 25   # safety cap; model exits naturally via native tool calling
SKILLS_SUMMARY_PATH  = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
LOG_DIR              = get_logs_dir()


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_main_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiniAgentFramework - web UI entrypoint.")
    parser.add_argument(
        "--model",
        type=str,
        default="20b",
        help="Ollama model alias or tag to use (e.g. '20b', 'llama3:8b').",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help="Context window for LLM calls.",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8000,
        metavar="PORT",
        help="Port for the web UI server (default 8000).",
    )
    parser.add_argument(
        "--api-host",
        type=str,
        default="0.0.0.0",
        metavar="HOST",
        help="Bind host for the web UI server (default 0.0.0.0).",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=os.environ.get("OLLAMA_HOST", ollama_client.DEFAULT_OLLAMA_HOST),
        metavar="URL",
        help="Ollama host URL. Defaults to http://localhost:11434. Also read from OLLAMA_HOST env var.",
    )
    parser.add_argument(
        "--chat-sequence-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="JSON file containing a prompt array to run as a shared-history exchange (test runner).",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: SESSION HELPERS
# ====================================================================================================
def _make_task_session(
    session_id: str,
    persist_path: Path,
    max_turns: int = 10,
) -> tuple[ConversationHistory, SessionContext]:
    """Create a ConversationHistory and SessionContext pair for one task or chat session."""
    history = ConversationHistory(max_turns=max_turns)
    ctx     = SessionContext(session_id=session_id, persist_path=persist_path)
    return history, ctx


# ====================================================================================================
# MARK: CHAT SEQUENCE MODE
# ====================================================================================================
def run_chat_sequence_mode(
    sequence_file: Path,
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Run a pre-defined sequence of prompts through a shared ConversationHistory + SessionContext.

    Used by the test wrapper to exercise multi-turn exchanges.  Outputs each turn in a
    structured format that the wrapper can parse:

        [TURN 1] User: <prompt>
        [TURN 1] Agent: <response>
        [TURN 1] tokens=<n> tps=<f>

    Exits with code 1 if the sequence file cannot be read or is malformed.
    """
    import json as _json
    import sys as _sys
    # Ensure subprocess stdout accepts full Unicode - Windows defaults to cp1252 which
    # can't encode characters the model commonly emits (e.g. \u202f, \u2011).
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        turns_raw = _json.loads(sequence_file.read_text(encoding="utf-8"))
        if not isinstance(turns_raw, list):
            raise ValueError("sequence file must contain a JSON array")
        prompts = [str(t) for t in turns_raw]
    except Exception as exc:
        print(f"[chat-sequence] Cannot load '{sequence_file}': {exc}", file=_sys.stderr)
        _sys.exit(1)

    history, session_ctx = _make_task_session(
        session_id   = log_path.stem,
        persist_path = get_chatsessions_day_dir() / f"{log_path.stem}.json",
    )

    for turn_idx, user_prompt in enumerate(prompts, start=1):
        print(f"[TURN {turn_idx}] User: {user_prompt}")
        logger.log_section_file_only(f"SEQUENCE TURN {turn_idx}")
        logger.log_file_only(f"User: {user_prompt}")

        slash_lines: list[str] = []
        seq_ctx = SlashCommandContext(
            config          = config,
            output          = lambda text, level="info", _buf=slash_lines: _buf.append(text),
            clear_history   = lambda: [history.clear(), session_ctx.clear()],
            session_context = session_ctx,
        )
        if handle_slash(user_prompt, seq_ctx):
            slash_response = "\n".join(slash_lines)
            print(f"[TURN {turn_idx}] Agent: {slash_response}")
            print(f"[TURN {turn_idx}] tokens=0 tps=0")
            logger.log_file_only(f"Agent: {slash_response}")
            history.add(user_prompt, slash_response)
            continue

        final_response, p_tokens, _c, run_success, tps = orchestrate_prompt(
            user_prompt=user_prompt,
            config=config,
            logger=logger,
            conversation_history=history.as_list() or None,
            session_context=session_ctx,
            quiet=True,
        )

        history.add(user_prompt, final_response)
        tps_str = f"{tps:.1f}" if tps > 0 else "0"
        print(f"[TURN {turn_idx}] Agent: {final_response}")
        print(f"[TURN {turn_idx}] tokens={p_tokens} tps={tps_str}")

        logger.log_file_only(f"Agent: {final_response}")
        if not run_success:
            logger.log_file_only("[WARN] Orchestration validation failed for this turn.")


# ====================================================================================================
# MARK: MAIN ENTRYPOINT
# ====================================================================================================
def main() -> None:
    args     = parse_main_args()
    log_path = create_log_file_path(log_dir=LOG_DIR)
    with SessionLogger(log_path) as logger:
        _run(args, logger, log_path)


# ----------------------------------------------------------------------------------------------------
def _run(args, logger, log_path) -> None:
    register_llm_call_logger(logger.log_file_only)

    # Set the active host once; all subsequent Ollama calls use this value.
    ollama_client.configure_host(args.ollama_host)

    # Ensure Ollama is running before starting the UI. For local hosts, ollama serve is
    # auto-started if needed. For remote/cloud hosts a warning is printed but startup
    # continues.
    try:
        ollama_client.ensure_ollama_running(verbose=True)
    except RuntimeError as exc:
        print(f"Warning: {exc}  LLM calls will fail until Ollama is reachable.", flush=True)

    # Resolve the alias (e.g. "20b") to a concrete installed model name.
    try:
        resolved_model = resolve_execution_model(args.model)
    except Exception:
        resolved_model = args.model

    skills_payload = load_skills_payload(SKILLS_SUMMARY_PATH)
    catalog_mtime  = SKILLS_SUMMARY_PATH.stat().st_mtime if SKILLS_SUMMARY_PATH.exists() else 0.0

    config = OrchestratorConfig(
        resolved_model      = resolved_model,
        num_ctx             = args.num_ctx,
        max_iterations      = MAX_ITERATIONS,
        skills_payload      = skills_payload,
        skills_summary_path = SKILLS_SUMMARY_PATH,
        catalog_mtime       = catalog_mtime,
    )

    ollama_client.register_session_config(resolved_model, args.num_ctx)

    logger.log_section("SYSTEM STATUS")
    logger.log(f"Ollama host:     {ollama_client.get_active_host()}")
    logger.log(f"Requested model: {args.model}")
    logger.log(f"Resolved model:  {resolved_model}")
    mode_label = (
        f"chat-sequence:{args.chat_sequence_file.name}" if args.chat_sequence_file else
        "api"
    )
    logger.log(f"Mode:            {mode_label}")
    logger.log(f"num_ctx:         {args.num_ctx}")
    logger.log(f"LLM timeout:     {get_llm_timeout()}s")
    logger.log(f"Max iterations:  {MAX_ITERATIONS}")
    try:
        logger.log(format_running_model_report(resolved_model))
    except Exception as exc:
        logger.log(f"Model runtime status: unavailable ({exc})")
    logger.log(f"Log file:        {log_path.as_posix()}")

    if args.chat_sequence_file:
        run_chat_sequence_mode(sequence_file=args.chat_sequence_file, config=config, logger=logger, log_path=log_path)
        return

    run_api_mode(config=config, logger=logger, log_path=log_path, host=args.api_host, port=args.api_port)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
