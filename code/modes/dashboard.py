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
#   dash-scheduler   detects due tasks and enqueues them into task_queue
#
# Chat submissions and scheduled tasks are both routed through scheduler.task_queue,
# which serialises them on a single worker thread.  Chat prompts are enqueued immediately;
# scheduled tasks are deduplicated so a task already in the queue is not added again.
# Slash commands (/help, /test, /task run, …) are also enqueued via task_queue.
#
# Conversation history for the chat panel is managed via ConversationHistory.
# Per-task history inside the scheduler loop is a fresh ConversationHistory per run.
#
# Related modules:
#   - orchestration.py       -- orchestrate_prompt, OrchestratorConfig, ConversationHistory
#   - scheduler.py           -- load_schedules_dir, is_task_due, task_queue
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

from chat_input import append_to_history as _append_chat_history
from chat_input import load_history as _load_chat_history
from ollama_client import get_active_host, get_active_num_ctx, get_llm_timeout, get_ollama_ps_rows
from orchestration import ConversationHistory
from orchestration import OrchestratorConfig
from orchestration import SessionContext
from orchestration import orchestrate_prompt
from runtime_logger import SessionLogger
from runtime_logger import create_log_file_path
from scheduler import initial_last_run, is_task_due
from scheduler import load_schedules_dir
from scheduler import task_queue
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from ui import colors as ui_colors
from ui.dashboard_app import DashboardApp
from workspace_utils import get_chatsessions_day_dir
from workspace_utils import get_chatsessions_dir
from workspace_utils import get_logs_dir
from workspace_utils import get_schedules_dir
from workspace_utils import get_workspace_root
from workspace_utils import trunc


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
    _dash_session_id = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    chat_session = SessionContext(
        session_id   = _dash_session_id,
        persist_path = get_chatsessions_day_dir() / f"{_dash_session_id}.json",
    )

    # ---------------------------------------------------------------------------
    # Chat-submit callback: called from the UI thread on each user submission.
    # ---------------------------------------------------------------------------
    def on_chat_submit(text: str) -> None:
        # Persist to history file and keep the in-memory list in sync for the input bar.
        _append_chat_history(text)
        if not _chat_history or _chat_history[-1] != text:
            _chat_history.append(text)

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
            chat_session.clear()

        dash_ctx = SlashCommandContext(
            config         = config,
            output         = _dash_output,
            clear_history  = _dash_clear_history,
            request_exit   = shutdown.set,
            session_context= chat_session,
        )
        if text.strip().startswith("/"):
            cmd_word   = text.strip().split()[0].lstrip("/")
            slash_name = f"slash_{cmd_word}_{datetime.now().strftime('%H%M%S%f')}"

            def _run_slash(_t: str = text, _ctx: SlashCommandContext = dash_ctx) -> None:
                handle_slash(_t, _ctx)

            state_now = task_queue.get_state()
            was_busy  = bool(state_now["active"] or state_now["pending"])
            if task_queue.enqueue(slash_name, "slash", _run_slash) and was_busy:
                active_name = state_now["active"]["name"] if state_now["active"] else "pending task"
                app.add_chat_line(f"Agent\u25b6 [queued - {active_name} in progress]", ui_colors.DIM)
            return

        def _run(_captured_text: str = text) -> None:
            app.add_chat_line(f"Agent\u25b6 [thinking... timeout {get_llm_timeout()}s]", ui_colors.DIM)
            response = ""
            p_tokens = 0
            tps_str  = ""
            try:
                run_log_path = create_log_file_path(log_dir=_LOG_DIR)
                with SessionLogger(run_log_path) as run_logger:
                    run_logger.log_section_file_only("DASHBOARD CHAT")
                    run_logger.log_file_only(f"User: {_captured_text}")

                    hist = chat_history.as_list() or None
                    response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                        user_prompt=_captured_text,
                        config=config,
                        logger=run_logger,
                        conversation_history=hist,
                        session_context=chat_session,
                        quiet=True,
                    )

                    tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                    run_logger.log_file_only(f"Agent: {response}")
                    run_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
            except Exception as exc:
                app.add_chat_line(f"Agent\u25b6 [Error: {exc}]", ui_colors.RED)
                return

            chat_history.add(_captured_text, response)
            app.add_chat_line(f"Agent\u25b6 {response}", ui_colors.NORMAL)
            app.add_chat_line(f"      [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)

        turn_name = f"chat_turn_{datetime.now().strftime('%H%M%S%f')}"
        state_now = task_queue.get_state()
        was_busy  = bool(state_now["active"] or state_now["pending"])
        if task_queue.enqueue(turn_name, "interactive", _run) and was_busy:
            active_name = state_now["active"]["name"] if state_now["active"] else "pending task"
            app.add_chat_line(f"Agent\u25b6 [queued - {active_name} in progress]", ui_colors.DIM)

    # ---------------------------------------------------------------------------
    _chat_history = _load_chat_history()
    app = DashboardApp(
        tasks=enabled_tasks,
        last_run=last_run,
        on_submit=on_chat_submit,
        shutdown_event=shutdown,
        task_queue=task_queue,
        chat_history_entries=_chat_history,
    )

    # ---- Background: ollama ps ----
    def _ollama_poll() -> None:
        while not shutdown.is_set():
            try:
                rows = get_ollama_ps_rows()
                if rows:
                    w_name = max((len(r.get('name', '')) for r in rows), default=10)
                    lines  = [f"  host: {get_active_host()}  |  ctx: {get_active_num_ctx():,}"]
                    lines.append(f"  {'NAME':<{w_name}}  {'SIZE':<12}  {'PROCESSOR':<12}  UNTIL")
                    for row in rows:
                        n = (row.get('name')      or '').ljust(w_name)
                        s = (row.get('size')      or '').ljust(12)
                        p = (row.get('processor') or '').ljust(12)
                        u =  row.get('until')     or ''
                        lines.append(f"  {n}  {s}  {p}  {u}")
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
                log_files = sorted(_LOG_DIR.glob("*/run_*.txt"))
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
                # Note: task dicts are compared by value; schedule fields like "cron" trigger a reload
                # but `last_run` is preserved so already-fired tasks are not re-run on the same tick.
                # Assumes schedule names are stable identifiers - a rename appears as remove+add.
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

                # Enqueue the task; the worker thread runs it when the LLM is free.
                # Use default-arg capture so loop variables are frozen at enqueue time.
                def _make_dash_task(_name=name, _prompts=list(prompts), _when=now) -> None:
                    app.record_run(_name, _when)
                    app.add_log_line(f"[SCHED] Starting: {_name}", ui_colors.MAGENTA)
                    app.add_chat_line(f"Sched\u25b6 Task started: {_name}", ui_colors.MAGENTA)
                    task_log_path = create_log_file_path(log_dir=_LOG_DIR)
                    with SessionLogger(task_log_path) as task_logger:
                        task_logger.log_section_file_only(f"SCHEDULER TASK (dashboard): {_name}")
                        try:
                            task_hist  = ConversationHistory()
                            task_ctx   = SessionContext(
                                session_id   = f"task_{_name}",
                                persist_path = get_chatsessions_dir() / f"task_{_name}.json",
                            )
                            sched_ctx  = SlashCommandContext(
                                config          = config,
                                output          = lambda text, level="info": task_logger.log_file_only(f"[slash/{level}] {text}"),
                                clear_history   = task_hist.clear,
                                session_context = task_ctx,
                            )
                            for step_index, prompt_text in enumerate(_prompts, start=1):
                                if shutdown.is_set():
                                    break
                                app.add_log_line(f"  [Step {step_index}] {trunc(prompt_text, 70)}", ui_colors.DIM)
                                task_logger.log_file_only(f"[Step {step_index}] {prompt_text}")
                                if handle_slash(prompt_text, sched_ctx):
                                    app.add_log_line("  [slash command handled]", ui_colors.DIM)
                                    continue
                                hist = task_hist.as_list() or None
                                response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                                    user_prompt=prompt_text,
                                    config=config,
                                    logger=task_logger,
                                    conversation_history=hist,
                                    session_context=task_ctx,
                                    quiet=True,
                                )
                                task_hist.add(prompt_text, response)
                                tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                                task_logger.log_file_only(f"[Step {step_index}] Agent: {response}")
                                task_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
                                app.add_log_line(f"  \u2713 [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)
                                app.add_chat_line(
                                    f"Sched\u25b6 [{_name} step {step_index}] {trunc(response, 100)}",
                                    ui_colors.BLUE,
                                )
                            task_logger.log_file_only(f"[DASHBOARD] Task '{_name}' completed.")
                            app.add_log_line(f"[SCHED] Done: {_name}", ui_colors.MAGENTA)
                        except Exception as exc:
                            app.add_log_line(f"[SCHED] Error in '{_name}': {exc}", ui_colors.RED)

                if task_queue.enqueue(name, "scheduled", _make_dash_task):
                    last_run[name] = now
                    app.add_log_line(f"[SCHED] Queued: {name}", ui_colors.MAGENTA)
                else:
                    app.add_log_line(f"[SCHED] '{name}' already queued - skipping", ui_colors.DIM)

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
    app.add_log_line("  Log tail started - waiting for entries...", ui_colors.DIM)

    try:
        app.run()   # blocks; exits when Ctrl+C sets shutdown or _running=False
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        shutdown.set()
        logger.log("[DASHBOARD] Stopped cleanly.")
