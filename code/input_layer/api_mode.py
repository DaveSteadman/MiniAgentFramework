# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# API execution mode for MiniAgentFramework.
#
# Provides run_api_mode(), which:
#   - Loads schedules and initialises the task queue
#   - Wires up api.py's push_log_line as the LLM-call log sink
#   - Starts a background scheduler thread so scheduled tasks fire
#   - Launches uvicorn to serve the FastAPI app
#
# Related modules:
#   - api.py              -- FastAPI app, all endpoints, setup(), push_log_line()
#   - main.py             -- creates config and calls run_api_mode()
#   - scheduler.py        -- task_queue, load_schedules_dir, is_task_due
#   - orchestration.py    -- orchestrate_prompt, OrchestratorConfig
#   - runtime_logger.py   -- SessionLogger, create_log_file_path
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import asyncio
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import agent_core.ollama_client as ollama_client
from agent_core.run_helpers import run_prompt_batch
from input_layer.api import app
from input_layer.api import push_log_line
from input_layer.api import setup as api_setup
from agent_core.orchestration import OrchestratorConfig
from utils.runtime_logger import SessionLogger
from utils.runtime_logger import create_log_file_path
from scheduler.scheduler import initial_last_run
from scheduler.scheduler import is_task_due
from scheduler.scheduler import load_schedules_dir
from scheduler.scheduler import task_queue
from utils.workspace_utils import get_chatsessions_day_dir
from utils.workspace_utils import get_logs_dir
from utils.workspace_utils import get_schedules_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SCHEDULES_DIR        = get_schedules_dir()
_LOG_DIR              = get_logs_dir()
_SCHEDULER_POLL_SECS  = 30
_DEFAULT_PORT         = 8000
_DEFAULT_HOST         = "0.0.0.0"


# ====================================================================================================
# MARK: API MODE
# ====================================================================================================

def run_api_mode(
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> None:
    """Launch the FastAPI server with background scheduler.

    Blocks until the user presses Ctrl+C or the process is terminated.
    All log output is broadcast to connected /logs/stream SSE clients as well
    as written to the log file.
    """
    import uvicorn

    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    shutdown = threading.Event()

    # Wire push_log_line into the LLM call logger so every orchestration log
    # line is also broadcast over the /logs/stream SSE endpoint.
    def _log_sink(text: str) -> None:
        logger.log_file_only(text)
        push_log_line(text)

    ollama_client.register_llm_call_logger(_log_sink)

    # Load schedules.
    tasks         = load_schedules_dir(_SCHEDULES_DIR)
    enabled_tasks = [t for t in tasks if t.get("enabled", True)]
    _startup      = datetime.now()
    last_run: dict[str, datetime | None] = {
        t["name"]: initial_last_run(t, _startup)
        for t in enabled_tasks
    }

    # Publish shared state to the API module.
    api_setup(
        config         = config,
        enabled_tasks  = enabled_tasks,
        last_run       = last_run,
        shutdown_event = shutdown,
    )

    # -----------------------------------------------------------------------
    # Background scheduler thread - identical logic to scheduler mode.
    # -----------------------------------------------------------------------
    def _scheduler_loop() -> None:
        while not shutdown.is_set():
            now = datetime.now()
            for task in enabled_tasks:
                if shutdown.is_set():
                    break
                name    = task["name"]
                prompts = task.get("prompts", [])
                if not prompts:
                    continue
                if not is_task_due(task, last_run.get(name), now):
                    continue

                def _run_task(_name=name, _prompts=list(prompts), _when=now) -> None:
                    push_log_line(f"[SCHEDULER] Starting task: {_name}")
                    try:
                        run_log_path = create_log_file_path(log_dir=_LOG_DIR)
                        with SessionLogger(run_log_path) as run_logger:
                            for prompt_text in _prompts:
                                current = prompt_text.get("prompt", "") if isinstance(prompt_text, dict) else str(prompt_text)
                                if current:
                                    push_log_line(f"[SCHEDULER] {_name}: {current[:80]}")
                            results = run_prompt_batch(
                                _prompts,
                                session_id=f"task_{_name}",
                                persist_path=get_chatsessions_day_dir() / f"task_{_name}.json",
                                config=config,
                                logger=run_logger,
                                quiet=True,
                                max_turns=10,
                            )
                            for item in results:
                                tps_str = f"{item['tps']:.1f}" if item["tps"] > 0 else "0"
                                push_log_line(f"[SCHEDULER] {_name}: done [{item['prompt_tokens']:,} tok, {tps_str} tok/s]")
                    except Exception as exc:
                        push_log_line(f"[SCHEDULER] {_name} error: {exc}")
                    last_run[_name] = _when
                    push_log_line(f"[SCHEDULER] Task '{_name}' completed.")

                if task_queue.enqueue(name, "scheduled", _run_task):
                    last_run[name] = now
                    push_log_line(f"[SCHEDULER] Task '{name}' queued.")

            for _ in range(_SCHEDULER_POLL_SECS * 2):
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    sched_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="api-scheduler")
    sched_thread.start()

    push_log_line(f"[API] Server starting on http://{host}:{port}")
    print(f"\nAPI mode - http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    print(f"Web UI:   http://localhost:{port}/", flush=True)

    uvicorn_config = uvicorn.Config(
        app     = app,
        host    = host,
        port    = port,
        log_level = "warning",  # suppress uvicorn access noise; our own logger handles it
    )
    server = uvicorn.Server(uvicorn_config)

    def _run_server() -> None:
        if sys.platform != "win32":
            server.run()
            return

        loop = asyncio.SelectorEventLoop() if hasattr(asyncio, "SelectorEventLoop") else asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def _exception_handler(loop_obj: asyncio.AbstractEventLoop, context: dict) -> None:
            exc    = context.get("exception")
            handle = context.get("handle")
            callback = getattr(handle, "_callback", None)
            cb_name  = getattr(callback, "__qualname__", repr(callback))
            if (
                isinstance(exc, ConnectionResetError)
                and getattr(exc, "winerror", None) == 10054
                and "_call_connection_lost" in str(cb_name)
            ):
                return
            loop_obj.default_exception_handler(context)

        loop.set_exception_handler(_exception_handler)
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()

    # Run uvicorn in a background thread. When server.run() is not on the main thread,
    # uvicorn's capture_signals() context manager detects the non-main thread and skips
    # all signal installation entirely, so it never calls signal.raise_signal() and the
    # CancelledError/KeyboardInterrupt tracebacks do not occur.
    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()

    # Main thread owns signal handling.
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        server.should_exit = True
        server_thread.join(timeout=10)
        print("\nAPI server stopped.", flush=True)
        logger.log("[API] Server stopped.")
