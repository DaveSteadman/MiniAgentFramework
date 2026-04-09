# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# CLI entrypoint for MiniAgentFramework.
#
# Starts the FastAPI server with the web UI and background scheduler.
#
# Core orchestration pipeline lives in orchestration.py.
# API/web mode lives in modes/api_mode.py.
#
# Related modules:
#   - orchestration.py          -- OrchestratorConfig, orchestrate_prompt
#   - modes/api_mode.py         -- run_api_mode (FastAPI + uvicorn + scheduler)
#   - ollama_client.py          -- Ollama server management and LLM calls
#   - skills_catalog_builder.py -- load_skills_payload, tool definitions
#   - utils/runtime_logger.py   -- SessionLogger, create_log_file_path
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import asyncio
import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path


# ----------------------------------------------------------------------------------------------------
def _maybe_reexec_into_project_venv() -> None:
    """Prefer the repository virtualenv interpreter when one exists.

    The app is often launched as `python code/main.py`, which depends on whichever
    global `python` happens to be first on PATH. That can diverge from the project's
    `.venv`, causing ambient system info and package resolution to be inconsistent.

    To keep startup automatic and deterministic, launch the repository `.venv`
    interpreter if it exists and we are not already running inside it. The parent
    process stays attached to the terminal and waits for the child so the shell
    does not regain control while the real server process is still running.
    Set MAF_SKIP_AUTO_VENV=1 to bypass.
    """
    if os.environ.get("MAF_SKIP_AUTO_VENV") == "1":
        return

    repo_root = Path(__file__).resolve().parent.parent
    venv_python = (
        repo_root / ".venv" / "Scripts" / "python.exe"
        if sys.platform.startswith("win")
        else repo_root / ".venv" / "bin" / "python"
    )
    if not venv_python.exists():
        return

    try:
        current_python = Path(sys.executable).resolve()
        target_python = venv_python.resolve()
    except Exception:
        return

    if current_python == target_python:
        return

    child_env = dict(os.environ)
    child_env["MAF_SKIP_AUTO_VENV"] = "1"
    cmd = [str(target_python), str(Path(__file__).resolve()), *sys.argv[1:]]

    child = subprocess.Popen(cmd, env=child_env)

    job_handle = None
    if sys.platform == "win32":
        try:
            job_handle = _attach_child_to_kill_on_close_job(child.pid)
        except Exception:
            job_handle = None

    try:
        raise SystemExit(child.wait())
    except KeyboardInterrupt:
        # If the child received the same terminal interrupt it should exit on its own.
        try:
            raise SystemExit(child.wait(timeout=5))
        except subprocess.TimeoutExpired:
            child.terminate()
            raise SystemExit(child.wait(timeout=5))
    finally:
        if job_handle is not None:
            ctypes.windll.kernel32.CloseHandle(job_handle)


# ----------------------------------------------------------------------------------------------------
def _attach_child_to_kill_on_close_job(pid: int):
    """On Windows, tie the child process lifetime to this launcher process."""
    kernel32 = ctypes.windll.kernel32

    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_SET_INFORMATION = 0x0200
    PROCESS_QUERY_INFORMATION = 0x0400
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError()

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        raise ctypes.WinError()

    process_handle = kernel32.OpenProcess(
        PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION,
        False,
        int(pid),
    )
    if not process_handle:
        kernel32.CloseHandle(job)
        raise ctypes.WinError()

    try:
        ok = kernel32.AssignProcessToJobObject(job, process_handle)
        if not ok:
            kernel32.CloseHandle(job)
            raise ctypes.WinError()
    finally:
        kernel32.CloseHandle(process_handle)

    return job


_maybe_reexec_into_project_venv()

import agent_core.ollama_client as ollama_client
from input_layer.api_mode import run_api_mode
from agent_core.ollama_client import format_running_model_report
from agent_core.ollama_client import get_llm_timeout
from agent_core.ollama_client import register_llm_call_logger
from agent_core.orchestration import OrchestratorConfig
from agent_core.orchestration import orchestrate_prompt
from agent_core.orchestration import resolve_execution_model
from agent_core.run_helpers import make_task_session
from agent_core.scratchpad import scratch_clear
from agent_core.skills_catalog_builder import load_skills_payload
from utils.runtime_logger import create_log_file_path
from utils.runtime_logger import SessionLogger
from input_layer.slash_commands import SlashCommandContext
from input_layer.slash_commands import handle as handle_slash
from utils.workspace_utils import get_bootstrap_defaults_file
from utils.workspace_utils import get_chatsessions_day_dir
from utils.workspace_utils import get_controldata_dir
from utils.workspace_utils import get_logs_dir
from utils.workspace_utils import get_user_data_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_NUM_CTX      = 131072
MAX_ITERATIONS       = 25   # safety cap; model exits naturally via native tool calling
SKILLS_CATALOG_PATH  = Path(__file__).resolve().parent / "agent_core" / "skills" / "skills_catalog.json"
LOG_DIR              = get_logs_dir()
DEFAULTS_FILE        = get_bootstrap_defaults_file()

# Keys accepted from default.json - must match the argparse dest names exactly.
_DEFAULTS_KEYS = {"model", "ctx", "agentport", "ollamahost"}

# All valid keys in default.json - superset of _DEFAULTS_KEYS.
# Keys here that are not in _DEFAULTS_KEYS are read directly by skills or slash commands
# and are not passed through argparse.
_KNOWN_KEYS = _DEFAULTS_KEYS | {"koredataurl", "ControlDataFolder", "UserDataFolder"}


# ====================================================================================================
# MARK: DEFAULTS LOADING
# ====================================================================================================
def _load_defaults() -> dict:
    # Returns only recognised keys from default.json.
    # Prints a startup warning listing any keys present in the file but not recognised.
    if not DEFAULTS_FILE.exists():
        return {}
    try:
        raw = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        accepted  = {k: v for k, v in raw.items() if k in _DEFAULTS_KEYS}
        unknown   = [k for k in raw if k not in _KNOWN_KEYS]
        if unknown:
            known_list = ", ".join(sorted(_KNOWN_KEYS))
            print(
                f"[default.json] Unrecognised key(s) ignored: {', '.join(sorted(unknown))}. "
                f"Recognised keys: {known_list}.",
                flush=True,
            )
        return accepted
    except Exception:
        return {}


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_main_args() -> argparse.Namespace:
    # Priority: factory defaults < default.json < command-line args.
    file_defaults = _load_defaults()

    parser = argparse.ArgumentParser(description="MiniAgentFramework - web UI entrypoint.")
    parser.add_argument(
        "--model",
        type=str,
        default="20b",
        help="Ollama model alias or tag to use (e.g. '20b', 'llama3:8b').",
    )
    parser.add_argument(
        "--ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help="Context window for LLM calls.",
    )
    parser.add_argument(
        "--agentport",
        type=int,
        default=8000,
        metavar="PORT",
        help="Port for the web UI server (default 8000). Always binds to 0.0.0.0.",
    )
    parser.add_argument(
        "--ollamahost",
        type=str,
        default=os.environ.get("OLLAMAHOST", ollama_client.DEFAULT_OLLAMAHOST),
        metavar="URL",
        help="Ollama host URL. Defaults to http://localhost:11434. Also read from OLLAMAHOST env var.",
    )
    # Apply file defaults between factory defaults and CLI; set_defaults() is overridden
    # by any explicit CLI value but overrides argparse's own default= values.
    if file_defaults:
        parser.set_defaults(**file_defaults)
    return parser.parse_args()


# ====================================================================================================
# MARK: SESSION HELPERS
# ====================================================================================================
# MARK: CHAT SEQUENCE MODE
# Used by test_wrapper.py via the CHAT_SEQUENCE_FILE environment variable (internal).
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

    history, session_ctx = make_task_session(
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
            clear_history   = lambda: [history.clear(), session_ctx.clear(), scratch_clear(session_ctx.session_id)],
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
    # When running as a subprocess (test_wrapper, pipe) Windows defaults stdout
    # to cp1252, which cannot encode the tick/cross characters printed in the
    # status block.  Reconfigure to UTF-8 early so all print() calls survive.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    register_llm_call_logger(logger.log_file_only)

    # Set the active host once; all subsequent Ollama calls use this value.
    ollama_client.configure_host(args.ollamahost)

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

    skills_payload = load_skills_payload(SKILLS_CATALOG_PATH)
    catalog_mtime  = SKILLS_CATALOG_PATH.stat().st_mtime if SKILLS_CATALOG_PATH.exists() else 0.0

    config = OrchestratorConfig(
        resolved_model      = resolved_model,
        num_ctx             = args.ctx,
        max_iterations      = MAX_ITERATIONS,
        skills_payload      = skills_payload,
        skills_catalog_path = SKILLS_CATALOG_PATH,
        catalog_mtime       = catalog_mtime,
    )

    ollama_client.register_session_config(resolved_model, args.ctx)

    _host_ok    = ollama_client.is_ollama_running()
    try:
        _known      = ollama_client.list_ollama_models()
        _model_ok   = resolved_model in _known
    except Exception:
        _model_ok   = False
    _cd = get_controldata_dir()
    _ud = get_user_data_dir()
    _tick = chr(0x2713)
    _cross = chr(0x2717)

    logger.log_section("SYSTEM STATUS")
    logger.log(f"Ollama host:     {ollama_client.get_active_host()} {_tick if _host_ok else _cross}")
    logger.log(f"Requested model: {args.model}")
    logger.log(f"Resolved model:  {resolved_model} {_tick if _model_ok else _cross}")
    print(f"Control data:    {_cd} {_tick if _cd.exists() else _cross}", flush=True)
    print(f"User data:       {_ud} {_tick if _ud.exists() else _cross}", flush=True)
    sequence_file_path = Path(os.environ["CHAT_SEQUENCE_FILE"]) if os.environ.get("CHAT_SEQUENCE_FILE") else None
    mode_label = (
        f"chat-sequence:{sequence_file_path.name}" if sequence_file_path else
        "api"
    )
    logger.log(f"Mode:            {mode_label}")
    logger.log(f"ctx:             {args.ctx}")
    logger.log(f"LLM timeout:     {get_llm_timeout()}s")
    logger.log(f"Max iterations:  {MAX_ITERATIONS}")
    try:
        logger.log(format_running_model_report(resolved_model))
    except Exception as exc:
        logger.log(f"Model runtime status: unavailable ({exc})")
    logger.log(f"Log file:        {log_path.as_posix()}")

    if sequence_file_path:
        run_chat_sequence_mode(sequence_file=sequence_file_path, config=config, logger=logger, log_path=log_path)
        return

    run_api_mode(config=config, logger=logger, log_path=log_path, host="0.0.0.0", port=args.agentport)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
