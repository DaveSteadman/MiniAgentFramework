# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# FastAPI application exposing the MiniAgentFramework engine as a REST + SSE service.
#
# Endpoints:
#   GET  /                          serve static web UI (index.html)
#   GET  /status/ollama             current 'ollama ps' model status
#   GET  /tasks                     enabled scheduled tasks with last-run and next-fire times
#   GET  /queue                     current task queue state
#   GET  /history                   last 20 input history entries (shared with TUI)
#   POST /history                   append an entry to input history
#   GET  /sessions/{id}/history     full conversation history for a session
#   POST /sessions/{id}/prompt      submit a new prompt (enqueues on task_queue)
#   GET  /logs/stream               SSE: tail all new log lines across all log files
#   GET  /runs/{id}/stream          SSE: stream events for a specific enqueued run
#
# SSE events are plain text/event-stream with a "data: <json>\n\n" envelope.
# All endpoints are CORS-open for localhost origins so the bundled static UI can reach them.
#
# Designed for --api mode: instantiated once in modes/api_mode.py, then served by uvicorn.
#
# Related modules:
#   - modes/api_mode.py       -- constructs and starts this app
#   - scheduler.py            -- task_queue singleton, load_schedules_dir, is_task_due
#   - orchestration.py        -- orchestrate_prompt, OrchestratorConfig, ConversationHistory
#   - runtime_logger.py       -- SessionLogger, create_log_file_path
#   - ollama_client.py        -- get_ollama_ps_rows, get_active_host
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import queue
import threading
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import sys
_code_dir = str(Path(__file__).resolve().parent)
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ollama_client
from ollama_client import get_active_host
from ollama_client import get_active_num_ctx
from ollama_client import get_ollama_ps_rows
from orchestration import ConversationHistory
from orchestration import OrchestratorConfig
from orchestration import SessionContext
from orchestration import orchestrate_prompt
from runtime_logger import SessionLogger
from runtime_logger import create_log_file_path
from chat_input import append_to_history
from chat_input import load_history
from scheduler import is_task_due
from scheduler import load_schedules_dir
from scheduler import task_queue
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from workspace_utils import get_chatsessions_day_dir
from workspace_utils import get_chatsessions_dir
from workspace_utils import get_logs_dir
from workspace_utils import get_schedules_dir
from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SCHEDULES_DIR       = get_schedules_dir()
_LOG_DIR             = get_logs_dir()
_WEB_DIR             = Path(__file__).resolve().parent / "ui" / "web"
_MAX_CHAT_HISTORY    = 10
_LOG_POLL_SECS       = 1.0      # how often the log-tail SSE generator checks for new lines
_LOG_TAIL_LINES      = 200      # how many historic lines to send on first connect


# ====================================================================================================
# MARK: GLOBAL STATE
# ====================================================================================================
# These are set once by api_mode.py before uvicorn starts.
_config:         OrchestratorConfig | None = None
_last_run:       dict[str, datetime | None] = {}
_enabled_tasks:  list[dict] = []
_shutdown_event: threading.Event = threading.Event()

# Per-run event queues: run_id -> queue.Queue[dict | None]
# None sentinel signals the stream is finished.
_run_event_queues: dict[str, queue.Queue] = {}
_run_queues_lock:  threading.Lock = threading.Lock()

# Global log broadcast queue - all log lines are pushed here for the /logs/stream SSE endpoint.
_log_broadcast:       queue.Queue = queue.Queue(maxsize=2000)


# ====================================================================================================
# MARK: SETUP FUNCTIONS
# ====================================================================================================

def setup(
    config: OrchestratorConfig,
    enabled_tasks: list[dict],
    last_run: dict[str, datetime | None],
    shutdown_event: threading.Event,
) -> None:
    """Called once by api_mode.py before serving. Stores shared state."""
    global _config, _enabled_tasks, _last_run, _shutdown_event
    _config         = config
    _enabled_tasks  = enabled_tasks
    _last_run       = last_run
    _shutdown_event = shutdown_event


# ====================================================================================================
# MARK: LOG BROADCAST
# ====================================================================================================

def push_log_line(line: str) -> None:
    """Push a log line into the global broadcast queue (non-blocking, drops oldest on overflow)."""
    try:
        _log_broadcast.put_nowait({"type": "log", "text": line, "ts": datetime.now().isoformat(timespec="seconds")})
    except queue.Full:
        try:
            _log_broadcast.get_nowait()
        except queue.Empty:
            pass
        try:
            _log_broadcast.put_nowait({"type": "log", "text": line, "ts": datetime.now().isoformat(timespec="seconds")})
        except queue.Full:
            pass


def _make_run_event_queue(run_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with _run_queues_lock:
        _run_event_queues[run_id] = q
    return q


def finish_run_event_queue(run_id: str) -> None:
    """Signal that a run is complete (sends None sentinel to all listeners)."""
    with _run_queues_lock:
        q = _run_event_queues.get(run_id)
    if q:
        try:
            q.put_nowait(None)
        except queue.Full:
            pass


# ====================================================================================================
# MARK: FASTAPI APP
# ====================================================================================================
app = FastAPI(title="MiniAgentFramework API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================================================
# MARK: STATIC FILES
# ====================================================================================================
if _WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")


# ----------------------------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def serve_index():
    index = _WEB_DIR / "index.html"
    if not index.exists():
        return {"error": "Web UI not found. Expected at code/ui/web/index.html"}
    return FileResponse(str(index))


# ====================================================================================================
# MARK: STATUS ENDPOINTS
# ====================================================================================================

@app.get("/status/ollama")
def get_ollama_status():
    """Return current Ollama host, context size, and running model rows from 'ollama ps'."""
    try:
        rows = get_ollama_ps_rows()
    except Exception as exc:
        rows = []
    return {
        "host":    get_active_host(),
        "num_ctx": get_active_num_ctx(),
        "rows":    rows,
        "ts":      datetime.now().isoformat(timespec="seconds"),
    }


# ====================================================================================================
# MARK: TASK ENDPOINTS
# ====================================================================================================

def _next_fire(task: dict, last: datetime | None, now: datetime) -> str | None:
    """Return a rough ISO next-fire time string, or None if unknown."""
    schedule = task.get("schedule", {})
    kind     = schedule.get("type", "")
    if kind == "interval":
        minutes = int(schedule.get("minutes", 60))
        base    = last if last else now
        nf      = base.replace(second=0, microsecond=0)
        while nf <= now:
            nf = nf + timedelta(minutes=minutes)
        return nf.isoformat(timespec="seconds")
    if kind == "daily":
        t_str = schedule.get("time", "00:00")
        h, m  = (int(x) for x in t_str.split(":"))
        nf    = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if nf <= now:
            nf = nf + timedelta(days=1)
        return nf.isoformat(timespec="seconds")
    return None


@app.get("/tasks")
def get_tasks():
    """Return enabled scheduled tasks with last-run and estimated next-fire times."""
    now    = datetime.now()
    result = []
    for task in _enabled_tasks:
        name  = task.get("name", "")
        last  = _last_run.get(name)
        entry = {
            "name":        name,
            "description": task.get("description", ""),
            "schedule":    task.get("schedule", {}),
            "last_run":    last.isoformat(timespec="seconds") if last else None,
            "next_fire":   _next_fire(task, last, now),
            "due_now":     is_task_due(task, last, now),
        }
        result.append(entry)
    return {"tasks": result, "ts": now.isoformat(timespec="seconds")}


@app.get("/queue")
def get_queue():
    """Return the current task queue state (active + pending)."""
    return task_queue.get_state()


# ====================================================================================================
# MARK: INPUT HISTORY ENDPOINTS
# ====================================================================================================

_HISTORY_LIMIT = 20


class HistoryAppendRequest(BaseModel):
    text: str


@app.get("/history")
def get_history():
    """Return the last _HISTORY_LIMIT input history entries (oldest-first)."""
    entries = load_history()
    return {"entries": entries[-_HISTORY_LIMIT:]}


@app.post("/history")
def post_history(body: HistoryAppendRequest):
    """Append one entry to the shared input history file."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")
    append_to_history(text)
    entries = load_history()
    return {"entries": entries[-_HISTORY_LIMIT:]}


# ====================================================================================================
# MARK: TIMELINE ENDPOINT
# ====================================================================================================

@app.get("/timeline")
def get_timeline(minutes_before: int = 40, minutes_after: int = 40):
    """Return a minute-resolution timeline centred on now.

    Each slot has: offset (int minutes from now), hhmm (str), is_now (bool),
    task_name (str | None), last_run (str | None).
    """
    now     = datetime.now()
    now_min = now.replace(second=0, microsecond=0)
    slots   = []

    for offset in range(-minutes_before, minutes_after + 1):
        slot_dt   = now_min + timedelta(minutes=offset)
        task_name = _task_at_slot(slot_dt, now_min)
        last      = None
        if task_name:
            lr = _last_run.get(task_name)
            last = lr.isoformat(timespec="seconds") if lr else None
        slots.append({
            "offset":    offset,
            "hhmm":      slot_dt.strftime("%H:%M"),
            "is_now":    offset == 0,
            "task_name": task_name,
            "last_run":  last,
        })

    # Also report active task from queue so the UI can mark it.
    q_state    = task_queue.get_state()
    active_now = q_state.get("active", {}) or {}
    return {
        "slots":       slots,
        "active_task": active_now.get("name"),
        "ts":          now.isoformat(timespec="seconds"),
    }


def _task_at_slot(slot_dt: datetime, now_min: datetime) -> str | None:
    """Return the name of the first task that fires at slot_dt, or None."""
    for task in _enabled_tasks:
        name  = task.get("name", "")
        sched = task.get("schedule", {})
        stype = sched.get("type", "")

        if stype == "daily":
            raw = sched.get("time", "00:00")
            try:
                hh, mm = map(int, raw.split(":"))
            except ValueError:
                continue
            fire_dt = slot_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if fire_dt == slot_dt:
                return name

        elif stype == "interval":
            interval_m = int(sched.get("minutes", 60))
            last       = _last_run.get(name)
            if last is None:
                # Would have fired at startup minute.
                if slot_dt == now_min:
                    return name
            else:
                next_fire = last.replace(second=0, microsecond=0) + timedelta(minutes=interval_m)
                if next_fire == slot_dt:
                    return name

    return None


# ====================================================================================================
# MARK: SESSION ENDPOINTS
# ====================================================================================================

class PromptRequest(BaseModel):
    prompt: str


@app.post("/sessions/{session_id}/prompt")
def post_prompt(session_id: str, body: PromptRequest):
    """Enqueue a prompt for a session. Returns the run_id immediately.

    Slash commands (inputs starting with '/') are routed through the slash command
    processor rather than orchestrate_prompt.
    """
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    if _config is None:
        raise HTTPException(status_code=503, detail="API not yet initialised")

    prompt_text = body.prompt.strip()
    run_id      = f"api_{session_id}_{datetime.now().strftime('%H%M%S%f')}"
    run_q       = _make_run_event_queue(run_id)

    persist = get_chatsessions_day_dir() / f"{session_id}.json"
    ctx     = SessionContext(session_id=session_id, persist_path=persist)
    history = _load_session_history(session_id)

    is_slash = prompt_text.startswith("/")

    def _run(_prompt=prompt_text) -> None:
        run_q.put_nowait({"type": "start", "run_id": run_id, "prompt": _prompt})
        try:
            if _prompt.startswith("/"):
                # Route through the slash command processor.
                output_lines: list[str] = []

                def _slash_output(text: str, level: str = "info") -> None:
                    output_lines.append(text)
                    push_log_line(f"[slash] {text}")

                slash_ctx = SlashCommandContext(
                    config          = _config,
                    output          = _slash_output,
                    clear_history   = lambda: (history.clear(), ctx.clear()),
                    session_context = ctx,
                )
                handled = handle_slash(_prompt, slash_ctx)
                response = "\n".join(output_lines) if output_lines else (
                    "(done)" if handled else f"Unknown command: {_prompt.split()[0]}"
                )
                run_q.put_nowait({
                    "type":     "response",
                    "run_id":   run_id,
                    "response": response,
                    "tokens":   0,
                    "tps":      "0",
                })
            else:
                log_path = create_log_file_path(log_dir=_LOG_DIR)
                with SessionLogger(log_path) as run_logger:
                    run_logger.log_section_file_only(f"API SESSION: {session_id}")
                    response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                        user_prompt          = _prompt,
                        config               = _config,
                        logger               = run_logger,
                        conversation_history = history.as_list() or None,
                        session_context      = ctx,
                        quiet                = True,
                    )
                    tps_str = f"{tps:.1f}" if tps > 0 else "0"
                    history.add(_prompt, response)
                    run_q.put_nowait({
                        "type":     "response",
                        "run_id":   run_id,
                        "response": response,
                        "tokens":   p_tokens,
                        "tps":      tps_str,
                    })
        except Exception as exc:
            run_q.put_nowait({"type": "error", "run_id": run_id, "message": str(exc)})
        finally:
            finish_run_event_queue(run_id)

    _display = prompt_text[:28] + ("..." if len(prompt_text) > 28 else "")
    task_queue.enqueue(_display, "api_slash" if is_slash else "api_chat", _run)
    return {"run_id": run_id, "session_id": session_id, "queued": True}


def _load_session_history(session_id: str) -> ConversationHistory:
    """Load existing conversation history for a session from its persist file if it exists."""
    history  = ConversationHistory(max_turns=_MAX_CHAT_HISTORY)
    day_dir  = get_chatsessions_day_dir()
    sessions_root = get_chatsessions_dir()

    # Check today's session file first, then fall back to any existing file anywhere.
    candidates = [
        day_dir / f"{session_id}.json",
        sessions_root / f"{session_id}.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                data  = json.loads(p.read_text(encoding="utf-8"))
                turns = data.get("turns", [])
                for t in turns:
                    up = t.get("user_prompt", "")
                    ar = t.get("assistant_response", "")
                    if up and ar:
                        history.add(up, ar)
            except Exception:
                pass
            break
    return history


@app.get("/sessions/{session_id}/history")
def get_session_history(session_id: str):
    """Return the conversation history for a session."""
    history = _load_session_history(session_id)
    return {"session_id": session_id, "turns": history.as_list()}


# ====================================================================================================
# MARK: LOG ENDPOINTS
# ====================================================================================================

@app.get("/logs")
def list_logs():
    """Return a listing of available log date directories and files."""
    result = []
    if _LOG_DIR.exists():
        for day_dir in sorted(_LOG_DIR.iterdir(), reverse=True):
            if day_dir.is_dir():
                files = sorted([f.name for f in day_dir.glob("*.txt")], reverse=True)
                result.append({"date": day_dir.name, "files": files})
    return {"log_dirs": result}


@app.get("/logs/{date}/{filename}")
def get_log_file(date: str, filename: str):
    """Return the content of a specific log file."""
    # Sanitise inputs - allow only safe characters to prevent path traversal.
    if not all(c.isalnum() or c in "-_." for c in date + filename):
        raise HTTPException(status_code=400, detail="Invalid path characters")
    log_path = _LOG_DIR / date / filename
    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")
    # Ensure the resolved path is still inside _LOG_DIR.
    try:
        log_path.resolve().relative_to(_LOG_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path outside log directory")
    return {"lines": log_path.read_text(encoding="utf-8", errors="replace").splitlines()}


# ====================================================================================================
# MARK: SSE HELPER
# ====================================================================================================

def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ====================================================================================================
# MARK: LOG STREAM SSE
# ====================================================================================================

@app.get("/logs/stream")
def stream_logs():
    """SSE endpoint: streams new log lines as they are broadcast via push_log_line()."""
    # Send the last N lines from the most recent log file as backfill.
    backfill: list[dict] = _get_log_backfill()

    def _generate():
        for item in backfill:
            yield _sse(item)

        # Stream live events until client disconnects (GeneratorExit) or shutdown.
        subscriber: queue.Queue = queue.Queue(maxsize=1000)
        _log_subscribers_lock.acquire()
        _log_subscribers.append(subscriber)
        _log_subscribers_lock.release()

        try:
            while not _shutdown_event.is_set():
                try:
                    item = subscriber.get(timeout=_LOG_POLL_SECS)
                    yield _sse(item)
                except queue.Empty:
                    # Send a keepalive comment so the browser doesn't time out.
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            _log_subscribers_lock.acquire()
            try:
                _log_subscribers.remove(subscriber)
            except ValueError:
                pass
            _log_subscribers_lock.release()

    return StreamingResponse(_generate(), media_type="text/event-stream")


# Fan-out: each SSE client gets its own subscriber queue fed by push_log_line.
_log_subscribers:      list[queue.Queue] = []
_log_subscribers_lock: threading.Lock    = threading.Lock()


def push_log_line(line: str) -> None:  # noqa: F811 - replaces module-level stub above
    """Push a log line to all active log-stream SSE subscribers."""
    item = {"type": "log", "text": line, "ts": datetime.now().isoformat(timespec="seconds")}
    with _log_subscribers_lock:
        for sub in list(_log_subscribers):
            try:
                sub.put_nowait(item)
            except queue.Full:
                pass


def _get_log_backfill() -> list[dict]:
    """Return the last _LOG_TAIL_LINES lines from the most recent log file."""
    if not _LOG_DIR.exists():
        return []
    day_dirs = sorted(_LOG_DIR.iterdir(), reverse=True)
    for day_dir in day_dirs:
        if not day_dir.is_dir():
            continue
        files = sorted(day_dir.glob("*.txt"), reverse=True)
        if files:
            try:
                lines = files[0].read_text(encoding="utf-8", errors="replace").splitlines()
                tail  = lines[-_LOG_TAIL_LINES:]
                return [{"type": "log", "text": ln, "ts": ""} for ln in tail]
            except Exception:
                return []
    return []


# ====================================================================================================
# MARK: RUN STREAM SSE
# ====================================================================================================

@app.get("/runs/{run_id}/stream")
def stream_run(run_id: str):
    """SSE endpoint: stream events for a specific run until it completes."""
    with _run_queues_lock:
        run_q = _run_event_queues.get(run_id)

    if run_q is None:
        raise HTTPException(status_code=404, detail="Run ID not found or already completed")

    def _generate():
        while True:
            try:
                item = run_q.get(timeout=2.0)
                if item is None:
                    # Sentinel: run finished.
                    yield _sse({"type": "done", "run_id": run_id})
                    break
                yield _sse(item)
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
