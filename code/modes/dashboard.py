# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Dashboard execution mode for MiniAgentFramework.
#
# Provides run_dashboard_mode(), which launches the interactive TUI:
#   - Top-left panel:  live 'ollama ps' model status (refreshed every 10 s)
#   - Top-right panel: scheduled-task timeline
#   - Bottom-left:     log tail (streams new lines from run_*.txt files every 2 s)
#   - Bottom-right:    multi-turn chat input
#
# Three background threads run concurrently while the UI is active:
#   dash-ollama      polls 'ollama ps' every 10 s and updates the model panel
#   dash-log-tail    streams new log lines every 2 s into the log panel
#   dash-scheduler   fires tasks from controldata/schedules/ on their schedules,
#                    respecting the shared llm_lock for single-LLM exclusivity
#
# Chat submissions dispatch orchestrate_prompt on a short-lived thread.
# Slash commands (/help, /model, /ctx, …) bypass orchestration entirely.
#
# Conversation history for the chat panel is managed via ConversationHistory.
# Per-task history inside the scheduler loop is a fresh ConversationHistory per run.
#
# Related modules:
#   - orchestration.py       -- orchestrate_prompt, OrchestratorConfig, ConversationHistory
#   - scheduler.py           -- load_schedules_dir, is_task_due, llm_lock
#   - ui/dashboard_app.py    -- DashboardApp TUI application
#   - slash_commands.py      -- handle(), SlashCommandContext
#   - runtime_logger.py      -- SessionLogger, create_log_file_path
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

from ollama_client import get_ollama_ps_rows
from orchestration import ConversationHistory
from orchestration import OrchestratorConfig
from orchestration import orchestrate_prompt
from runtime_logger import SessionLogger
from runtime_logger import create_log_file_path
from scheduler import initial_last_run, is_task_due
from scheduler import llm_lock
from scheduler import load_schedules_dir
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from ui import colors as ui_colors
from ui.dashboard_app import DashboardApp
from workspace_utils import get_logs_dir
from workspace_utils import get_schedules_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SCHEDULES_DIR        = get_schedules_dir()
_LOG_DIR              = get_logs_dir()
_SCHEDULER_POLL_SECS  = 30
_MAX_CHAT_HISTORY     = 10    # maximum user/assistant turn pairs to keep in the chat panel


# ====================================================================================================
# MARK: DASHBOARD MODE
# ====================================================================================================
def run_dashboard_mode(
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Launch the interactive dashboard (timeline + log tail + chat).

    Blocks until the user quits (Ctrl+C or the dashboard's own shutdown mechanism).
    """
    shutdown = threading.Event()

    tasks         = load_schedules_dir(_SCHEDULES_DIR)
    enabled_tasks = [t for t in tasks if t.get("enabled", True)]
    _startup      = datetime.now()
    last_run: dict[str, datetime | None] = {
        t["name"]: initial_last_run(t, _startup)
        for t in enabled_tasks
    }

    chat_history = ConversationHistory(max_turns=_MAX_CHAT_HISTORY)

    # ---------------------------------------------------------------------------
    # Chat-submit callback: called from the UI thread on each user submission.
    # ---------------------------------------------------------------------------
    def on_chat_submit(text: str) -> None:
        app.add_chat_line(f"You  \u25b6 {text}", ui_colors.INPUT)
        app.set_active_tab(DashboardApp.TAB_CHAT)

        _level_colors = {
            'info':    ui_colors.BLUE,
            'item':    ui_colors.NORMAL,
            'error':   ui_colors.RED,
            'success': ui_colors.MAGENTA,
            'dim':     ui_colors.DIM,
        }

        def _dash_output(text: str, level: str = 'info') -> None:
            prefix = "Agent\u25b6 " if level in ('info', 'error', 'success') else "      "
            app.add_chat_line(f"{prefix}{text}", _level_colors.get(level, ui_colors.NORMAL))

        def _dash_clear_history() -> None:
            chat_history.clear()

        dash_ctx = SlashCommandContext(
            config        = config,
            output        = _dash_output,
            clear_history = _dash_clear_history,
            request_exit  = shutdown.set,
        )
        if handle_slash(text, dash_ctx):
            return

        def _run() -> None:
            if not llm_lock.acquire(blocking=False):
                app.add_chat_line(
                    "Agent\u25b6 [LLM busy please wait]",
                    ui_colors.RED,
                )
                return
            response = ""
            p_tokens = 0
            tps_str  = ""
            try:
                run_log_path = create_log_file_path(log_dir=_LOG_DIR)
                run_logger   = SessionLogger(run_log_path)
                run_logger.log_section_file_only("DASHBOARD CHAT")
                run_logger.log_file_only(f"User: {text}")

                hist = chat_history.as_list() or None
                response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                    user_prompt=text,
                    config=config,
                    logger=run_logger,
                    conversation_history=hist,
                    quiet=True,
                )

                tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                run_logger.log_file_only(f"Agent: {response}")
                run_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
            except Exception as exc:
                app.add_chat_line(f"Agent\u25b6 [Error: {exc}]", ui_colors.RED)
                return
            finally:
                llm_lock.release()

            chat_history.add(text, response)

            app.add_chat_line(f"Agent\u25b6 {response}", ui_colors.NORMAL)
            app.add_chat_line(f"      [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)

        threading.Thread(target=_run, daemon=True, name="chat-dispatch").start()

    # ---------------------------------------------------------------------------
    app = DashboardApp(
        tasks=enabled_tasks,
        last_run=last_run,
        on_submit=on_chat_submit,
        shutdown_event=shutdown,
        llm_lock=llm_lock,
    )

    # ---- Background: ollama ps ----
    def _ollama_poll() -> None:
        while not shutdown.is_set():
            try:
                rows = get_ollama_ps_rows()
                if rows:
                    w_name = max((len(r.get('name', '')) for r in rows), default=10)
                    header = f"{'NAME':<{w_name}}  SIZE        PROCESSOR   UNTIL"
                    lines  = [header]
                    for row in rows:
                        n = (row.get('name')      or '').ljust(w_name)
                        s = (row.get('size')      or '').ljust(10)
                        p = (row.get('processor') or '').ljust(10)
                        u =  row.get('until')     or ''
                        lines.append(f"{n}  {s}  {p}  {u}")
                    app.set_ollama_lines(lines)
                else:
                    app.set_ollama_lines(["  (no models currently loaded)"])
            except Exception as exc:
                app.set_ollama_lines([f"  ollama ps: {exc}"])
            for _ in range(20):    # 10 s in 0.5 s steps
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # ---- Background: log tail ----
    def _log_tail() -> None:
        watched: Path | None = None
        pos = 0
        while not shutdown.is_set():
            try:
                log_files = sorted(_LOG_DIR.glob("run_*.txt"))
                if log_files:
                    latest = log_files[-1]
                    if latest != watched:
                        watched = latest
                        pos     = 0
                        app.add_log_line(f"\u2500\u2500\u2500 {latest.name} \u2500\u2500\u2500", ui_colors.BLUE)
                    size = latest.stat().st_size
                    if size > pos:
                        with latest.open(encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            new_text = fh.read()
                            pos = fh.tell()  # use actual read position, not stale stat size
                        for line in new_text.splitlines():
                            app.add_log_line(line, ui_colors.DIM)
            except Exception:
                pass
            for _ in range(4):     # 2 s in 0.5 s steps
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # ---- Background: scheduler ----
    def _scheduler_loop() -> None:
        nonlocal enabled_tasks
        while not shutdown.is_set():
            # -- Reload schedule files and apply changes --
            try:
                fresh_tasks     = load_schedules_dir(_SCHEDULES_DIR)
                fresh_enabled   = [t for t in fresh_tasks if t.get("enabled", True)]
                fresh_by_name   = {t["name"]: t for t in fresh_enabled}
                current_by_name = {t["name"]: t for t in enabled_tasks}

                added   = [n for n in fresh_by_name   if n not in current_by_name]
                removed = [n for n in current_by_name if n not in fresh_by_name]
                changed = [
                    n for n in fresh_by_name
                    if n in current_by_name and fresh_by_name[n] != current_by_name[n]
                ]

                if added or removed or changed:
                    _reload_now = datetime.now()
                    for n in added:
                        last_run[n] = initial_last_run(fresh_by_name[n], _reload_now)
                        app.add_log_line(f"[SCHED] New task loaded: {n}", ui_colors.MAGENTA)
                    for n in removed:
                        last_run.pop(n, None)
                        app.add_log_line(f"[SCHED] Task removed: {n}", ui_colors.DIM)
                    for n in changed:
                        last_run[n] = last_run.get(n)
                        app.add_log_line(f"[SCHED] Task updated: {n}", ui_colors.DIM)
                    enabled_tasks = fresh_enabled
                    app.tasks = enabled_tasks
            except Exception as exc:
                app.add_log_line(f"[SCHED] Schedule reload error: {exc}", ui_colors.RED)

            now = datetime.now()
            for task in enabled_tasks:
                if shutdown.is_set():
                    break
                name    = task["name"]
                prompts = task.get("prompts", [])
                if not prompts:
                    continue
                if not is_task_due(task, last_run[name], now):
                    continue

                if not llm_lock.acquire(blocking=False):
                    app.add_log_line(f"[SCHED] '{name}' due but LLM busy — will retry next cycle", ui_colors.DIM)
                    continue

                # Lock is now held — record start time and run the task.
                last_run[name] = now
                app.add_log_line(f"[SCHED] Starting: {name}", ui_colors.MAGENTA)
                app.add_chat_line(f"Sched▶ Task started: {name}", ui_colors.MAGENTA)

                task_log_path = create_log_file_path(log_dir=_LOG_DIR)
                task_logger   = SessionLogger(task_log_path)
                task_logger.log_section_file_only(f"SCHEDULER TASK (dashboard): {name}")

                try:
                    task_hist  = ConversationHistory()
                    sched_ctx  = SlashCommandContext(
                        config        = config,
                        output        = lambda text, level='info': task_logger.log_file_only(f"[slash/{level}] {text}"),
                        clear_history = task_hist.clear,
                    )
                    for step_index, prompt_text in enumerate(prompts, start=1):
                        if shutdown.is_set():
                            break
                        app.add_log_line(f"  [Step {step_index}] {prompt_text[:70]}", ui_colors.DIM)
                        task_logger.log_file_only(f"[Step {step_index}] {prompt_text}")

                        if handle_slash(prompt_text, sched_ctx):
                            app.add_log_line(f"  [slash command handled]", ui_colors.DIM)
                            continue

                        hist = task_hist.as_list() or None
                        response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                            user_prompt=prompt_text,
                            config=config,
                            logger=task_logger,
                            conversation_history=hist,
                            quiet=True,
                        )
                        task_hist.add(prompt_text, response)

                        tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                        task_logger.log_file_only(f"[Step {step_index}] Agent: {response}")
                        task_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
                        app.add_log_line(f"  \u2713 [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)
                        app.add_chat_line(
                            f"Sched\u25b6 [{name} step {step_index}] {response[:100]}",
                            ui_colors.BLUE,
                        )

                    task_logger.log_file_only(f"[DASHBOARD] Task '{name}' completed.")
                    app.add_log_line(f"[SCHED] Done: {name}", ui_colors.MAGENTA)
                finally:
                    llm_lock.release()

            for _ in range(_SCHEDULER_POLL_SECS * 2):
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # Register a SIGINT fallback in case the OS delivers it before kbhit sees it.
    original_sigint = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame):  # noqa: ARG001
        shutdown.set()

    signal.signal(signal.SIGINT, _sigint_handler)

    threading.Thread(target=_ollama_poll,    daemon=True, name="dash-ollama").start()
    threading.Thread(target=_log_tail,       daemon=True, name="dash-log-tail").start()
    threading.Thread(target=_scheduler_loop, daemon=True, name="dash-scheduler").start()

    app.add_chat_line("  MiniAgentFramework Dashboard", ui_colors.TITLE)
    app.add_chat_line(
        f"  Model: {config.resolved_model}  |  Tab = Log\u2194Chat  |  Ctrl+C to stop",
        ui_colors.DIM,
    )
    app.add_log_line("  Log tail started \u2014 waiting for entries...", ui_colors.DIM)

    try:
        app.run()   # blocks; exits when Ctrl+C sets shutdown or _running=False
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        shutdown.set()
        logger.log("[DASHBOARD] Stopped cleanly.")
