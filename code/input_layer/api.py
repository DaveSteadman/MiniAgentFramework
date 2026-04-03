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
#   GET  /logs/file?path=<path>      SSE: tail a specific log file (used for per-run view)
#   GET  /runs/{id}/stream          SSE: stream events for a specific enqueued run
#
# SSE events are plain text/event-stream with a "data: <json>\n\n" envelope.
# CORS is restricted to localhost origins only - requests from external sites are blocked.
#
# Instantiated once in modes/api_mode.py, then served by uvicorn.
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
# sys.path must be configured before any project imports.
import sys
from pathlib import Path

_code_dir = str(Path(__file__).resolve().parent.parent)
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

import json
import queue
import re
import threading
import time
import uuid
from datetime import datetime
from datetime import timedelta

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_core.ollama_client import get_active_host
from agent_core.ollama_client import get_active_model
from agent_core.ollama_client import get_active_num_ctx
from agent_core.ollama_client import get_ollama_ps_rows
from agent_core.orchestration import ConversationHistory
from agent_core.orchestration import OrchestratorConfig
from agent_core.orchestration import SessionContext
from agent_core.orchestration import get_sandbox_enabled
from agent_core.orchestration import orchestrate_prompt
from agent_core.orchestration import request_stop
from agent_core.orchestration import set_sandbox_enabled
from utils.runtime_logger import SessionLogger
from utils.runtime_logger import create_log_file_path
from input_layer.chat_input import append_to_history
from input_layer.chat_input import load_history
from scheduler.scheduler import is_task_due
from scheduler.scheduler import task_queue
from input_layer.slash_commands import SlashCommandContext
from input_layer.slash_commands import handle as handle_slash
from utils.workspace_utils import get_chatsessions_day_dir
from utils.workspace_utils import get_chatsessions_dir
from utils.workspace_utils import get_chatsessions_named_dir
from utils.workspace_utils import get_logs_dir
from utils.version import __version__


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Run-event streaming patterns - compiled once and reused across all prompt runs.
_LOG_FILE_RE      = re.compile(r"^Log file:\s*(.+)$")
_TURN_AGENT_RE    = re.compile(r"^\[TURN\s+(\d+)\]\s+Agent:\s*(.*)$")
_TURN_METRICS_RE  = re.compile(r"^\[TURN\s+(\d+)\]\s+tokens=(\d+)\s+tps=([0-9.]+)$")
_TEST_COMPLETE_RE = re.compile(r"^\[(TEST COMPLETE|ALL TESTS COMPLETE)\]\s+(.+)$")

_LOG_DIR             = get_logs_dir()
_WEB_DIR             = Path(__file__).resolve().parent / "ui"
_COMPACT_FILL_PCT    = 0.75  # compact when prompt-token fill reaches this fraction of num_ctx
_QUEUE_PREVIEW_LIMIT = 10
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

_latest_log_path: str | None = None


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


def _set_latest_log_path(path: str | Path | None) -> None:
    global _latest_log_path
    _latest_log_path = str(path) if path else None


def _make_run_event_queue(run_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=2000)
    with _run_queues_lock:
        _run_event_queues[run_id] = q
    return q


def _queue_run_event(run_q: queue.Queue, event: dict | None, priority: bool = False) -> None:
    try:
        run_q.put_nowait(event)
        return
    except queue.Full:
        if not priority:
            return

    while True:
        try:
            dropped = run_q.get_nowait()
            if dropped is None:
                # Sentinel marks stream completion - reinsert it and stop draining.
                # Discarding it would cause the SSE consumer to wait forever.
                try:
                    run_q.put_nowait(None)
                except queue.Full:
                    pass
                return
        except queue.Empty:
            return

        try:
            run_q.put_nowait(event)
            return
        except queue.Full:
            continue


def _validate_session_id(session_id: str) -> None:
    """Raise HTTP 400 if session_id contains characters that could form a path traversal."""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id: use only letters, digits, hyphens and underscores")


def finish_run_event_queue(run_id: str) -> None:
    """Signal that a run is complete by sending None sentinel to the queue.

    Does NOT pop the queue entry here - stream_run's _generate() does that when it receives
    the sentinel. This is critical: fast runs (e.g. slash commands completing in milliseconds)
    must keep the queue entry alive so the SSE client can still connect and read all events.
    """
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

# Restrict CORS to localhost only. External pages cannot trigger prompt or history endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================================================
# MARK: STATIC FILES
# ====================================================================================================
# All static UI files are served with Cache-Control: no-store so the browser always fetches
# the current version from disk. Do NOT use StaticFiles mount for these - Starlette mounts
# take routing priority over explicit handlers, which prevents the no-store header being set.

@app.get("/", include_in_schema=False)
def serve_index():
    index = _WEB_DIR / "index.html"
    if not index.exists():
        return {"error": "Web UI not found"}
    return FileResponse(str(index), headers={"Cache-Control": "no-store"})


@app.get("/static/app.js", include_in_schema=False)
def serve_app_js():
    return FileResponse(str(_WEB_DIR / "app.js"), headers={"Cache-Control": "no-store"})


@app.get("/static/style.css", include_in_schema=False)
def serve_style_css():
    return FileResponse(str(_WEB_DIR / "style.css"), headers={"Cache-Control": "no-store"})


# ====================================================================================================
# MARK: STATUS ENDPOINTS
# ====================================================================================================

@app.get("/version")
def get_version():
    """Return the framework version string."""
    return {"version": __version__}


@app.get("/status/ollama")
def get_ollama_status():
    """Return current Ollama host, context size, and running model rows from 'ollama ps'."""
    try:
        rows = get_ollama_ps_rows()
    except Exception as exc:
        rows = []
    return {
        "host":    get_active_host(),
        "model":   get_active_model(),
        "num_ctx": get_active_num_ctx(),
        "rows":    rows,
        "ts":      datetime.now().isoformat(timespec="seconds"),
    }


# ====================================================================================================
# MARK: SETTINGS ENDPOINTS
# ====================================================================================================

@app.get("/settings/sandbox")
def settings_sandbox_get():
    """Return the current Python execution sandbox state."""
    return {"sandbox": get_sandbox_enabled()}


@app.post("/settings/sandbox")
def settings_sandbox_post(enabled: bool):
    """Set the Python execution sandbox state."""
    set_sandbox_enabled(enabled)
    return {"sandbox": get_sandbox_enabled()}


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
    """Return the total queued prompt count and the next prompts to be serviced."""
    queue_state = task_queue.get_state(pending_limit=_QUEUE_PREVIEW_LIMIT)
    return {
        "queued_prompt_count": queue_state.get("queued_prompt_count", 0),
        "next_prompts":        queue_state.get("next_prompts", []),
        "next_prompts_limit":  queue_state.get("next_prompts_limit", _QUEUE_PREVIEW_LIMIT),
        "updated_at":          queue_state.get("updated_at"),
    }


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
# MARK: STOPRUN
# ====================================================================================================
# /stoprun is the only slash command that bypasses the task queue entirely.
# It executes immediately inside post_prompt so it can act on the currently-running
# LLM call without waiting for it to finish.  Two things happen:
#   1. request_stop() sets a threading.Event that orchestrate_prompt() checks between
#      rounds - the current HTTP call to Ollama finishes naturally, then the loop exits.
#   2. clear_pending() drains every not-yet-started item from the task queue and returns
#      their run_ids so we can push cancellation events to their SSE clients.

def _handle_stoprun_immediate(run_id: str, run_q: "queue.Queue") -> None:
    """Immediately signal the active run to stop and cancel all pending queue items."""
    # Signal the orchestration loop to exit after its current LLM round.
    request_stop()

    # Drain all pending items from the task queue.
    cancelled_ids = task_queue.clear_pending()

    # Push a cancellation response + sentinel to each pending run's SSE client.
    cancel_msg = "Cancelled by /stoprun."
    with _run_queues_lock:
        for rid in cancelled_ids:
            q = _run_event_queues.get(rid)
            if q is None:
                continue
            try:
                q.put_nowait({"type": "response", "run_id": rid, "response": cancel_msg, "tokens": 0, "tps": "0"})
            except queue.Full:
                pass
            try:
                q.put_nowait(None)
            except queue.Full:
                pass

    n = len(cancelled_ids)
    active_note = "Active run will halt after its current LLM round. " if True else ""
    summary = (
        f"{active_note}{n} pending prompt{'s' if n != 1 else ''} cancelled."
        if n else
        f"{active_note}No prompts were queued."
    )
    _queue_run_event(run_q, {"type": "response", "run_id": run_id, "response": summary, "tokens": 0, "tps": "0"}, priority=True)
    finish_run_event_queue(run_id)


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
    _validate_session_id(session_id)

    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    if _config is None:
        raise HTTPException(status_code=503, detail="API not yet initialised")

    prompt_text = body.prompt.strip()
    run_id      = f"api_{session_id}_{uuid.uuid4().hex}"
    run_q       = _make_run_event_queue(run_id)

    # /stoprun is handled immediately - it must not join the queue because its
    # entire purpose is to act on the currently-running and pending items.
    if prompt_text.lower() == "/stoprun":
        _handle_stoprun_immediate(run_id, run_q)
        return {"run_id": run_id, "session_id": session_id, "queued": True}

    def _run(_prompt=prompt_text) -> None:
        # Load history and session context at execution time, not enqueue time.
        # This prevents rapid back-to-back requests from overwriting each other's turns.
        persist             = get_chatsessions_day_dir() / f"{session_id}.json"
        ctx                 = SessionContext(session_id=session_id, persist_path=persist)
        history, summaries  = _load_session(session_id)
        _queue_run_event(run_q, {"type": "start", "run_id": run_id, "prompt": _prompt}, priority=True)
        try:
            if _prompt.startswith("/"):
                # Route through the slash command processor.
                output_lines: list[str] = []
                streamed_output = False

                def _slash_output(text: str, level: str = "info") -> None:
                    nonlocal streamed_output
                    output_lines.append(text)
                    push_log_line(f"[slash] {text}")

                    log_match = _LOG_FILE_RE.match(text.strip())
                    if log_match:
                        log_path = log_match.group(1).strip()
                        _set_latest_log_path(log_path)
                        _queue_run_event(run_q, {
                            "type":   "log_file",
                            "run_id": run_id,
                            "path":   log_path,
                        }, priority=True)
                        streamed_output = True
                        return

                    agent_match = _TURN_AGENT_RE.match(text)
                    if agent_match:
                        _queue_run_event(run_q, {
                            "type":     "test_agent_response",
                            "run_id":   run_id,
                            "turn":     int(agent_match.group(1)),
                            "response": agent_match.group(2),
                        }, priority=True)
                        streamed_output = True
                        return

                    metrics_match = _TURN_METRICS_RE.match(text)
                    if metrics_match:
                        _queue_run_event(run_q, {
                            "type":   "test_agent_metrics",
                            "run_id": run_id,
                            "turn":   int(metrics_match.group(1)),
                            "tokens": int(metrics_match.group(2)),
                            "tps":    metrics_match.group(3),
                        }, priority=True)
                        streamed_output = True
                        return

                    test_complete_match = _TEST_COMPLETE_RE.match(text)
                    if test_complete_match:
                        _queue_run_event(run_q, {
                            "type":   "test_complete",
                            "run_id": run_id,
                            "text":   text,
                            "level":  level,
                        }, priority=True)
                        streamed_output = True
                        return

                    _queue_run_event(run_q, {
                        "type":   "progress",
                        "run_id": run_id,
                        "text":   text,
                        "level":  level,
                    })
                    streamed_output = True

                def _do_switch_session(new_session_id: str, name: str) -> None:
                    _queue_run_event(run_q, {
                        "type":       "switch_session",
                        "run_id":     run_id,
                        "session_id": new_session_id,
                        "name":       name,
                    }, priority=True)

                def _do_rename_session(new_session_id: str, name: str) -> None:
                    _queue_run_event(run_q, {
                        "type":       "rename_session",
                        "run_id":     run_id,
                        "session_id": new_session_id,
                        "name":       name,
                    }, priority=True)

                slash_ctx = SlashCommandContext(
                    config          = _config,
                    output          = _slash_output,
                    clear_history   = lambda: (history.clear(), ctx.clear(), _save_session(session_id, history, [], 0, 0)),
                    session_context = ctx,
                    session_id      = session_id,
                    switch_session  = _do_switch_session,
                    rename_session  = _do_rename_session,
                )
                handled = handle_slash(_prompt, slash_ctx)
                if not streamed_output:
                    response = "\n".join(output_lines) if output_lines else (
                        "(done)" if handled else f"Unknown command: {_prompt.split()[0]}"
                    )
                    _queue_run_event(run_q, {
                        "type":     "response",
                        "run_id":   run_id,
                        "response": response,
                        "tokens":   0,
                        "tps":      "0",
                    }, priority=True)
            else:
                log_path = create_log_file_path(log_dir=_LOG_DIR)
                _set_latest_log_path(log_path)
                # Notify the run stream client which log file to tail.
                _queue_run_event(run_q, {"type": "log_file", "run_id": run_id, "path": str(log_path)}, priority=True)
                with SessionLogger(log_path) as run_logger:
                    run_logger.log_section_file_only(f"API SESSION: {session_id}")
                    summary_block = _build_summary_block(summaries)
                    response, p_tokens, _c, _ok, tps = orchestrate_prompt(
                        user_prompt           = _prompt,
                        config                = _config,
                        logger                = run_logger,
                        conversation_history  = history.as_list() or None,
                        session_context       = ctx,
                        quiet                 = True,
                        conversation_summary  = summary_block or None,
                    )
                    tps_str = f"{tps:.1f}" if tps > 0 else "0"
                    history.add(_prompt, response)
                    summaries = _save_session(session_id, history, summaries, p_tokens, get_active_num_ctx())
                    _queue_run_event(run_q, {
                        "type":     "response",
                        "run_id":   run_id,
                        "response": response,
                        "tokens":   p_tokens,
                        "tps":      tps_str,
                    }, priority=True)
        except Exception as exc:
            _queue_run_event(run_q, {"type": "error", "run_id": run_id, "message": str(exc)}, priority=True)
        finally:
            finish_run_event_queue(run_id)

    # Use run_id as the queue name so identical prompts submitted in quick succession
    # are never deduplicated - dedup only makes sense for scheduled tasks, not user input.
    task_queue.enqueue(run_id, "api_chat", _run, label=prompt_text[:48])
    return {"run_id": run_id, "session_id": session_id, "queued": True}


def _session_path(session_id: str) -> Path:
    """Return the canonical session file path - named/ subfolder first, then root."""
    named = get_chatsessions_named_dir() / f"{session_id}.json"
    if named.exists():
        return named
    return get_chatsessions_dir() / f"{session_id}.json"


def _load_session(session_id: str) -> tuple["ConversationHistory", list[dict]]:
    """Load conversation history and summary blocks from the session file.

    Returns (ConversationHistory, summaries) where summaries is a list of
    {"text": str, "turn_range": [int, int]} dicts covering older exchanges that
    have been compacted.  Falls back to legacy date-scoped files on first run.
    """
    history   = ConversationHistory()  # unlimited - compaction governs retention
    summaries: list[dict] = []
    path      = _session_path(session_id)

    # Fall back to legacy date-dir file if no root canonical file exists yet.
    if not path.exists():
        legacy = get_chatsessions_day_dir() / f"{session_id}.json"
        if legacy.exists():
            path = legacy

    if path.exists():
        try:
            data      = json.loads(path.read_text(encoding="utf-8"))
            summaries = data.get("summaries", [])
            for t in data.get("turns", []):
                up = t.get("user_prompt", "")
                ar = t.get("assistant_response", "")
                if up and ar:
                    history.add(up, ar)
        except Exception:
            pass
    return history, summaries


def _compact_old_turns(turns: list[dict], summaries: list[dict], batch_size: int) -> tuple[list[dict], list[dict]]:
    """Compress the oldest batch_size turns into a summary block via an isolated LLM call.

    Returns (remaining_turns, updated_summaries).  Returns inputs unchanged on any error
    (no model loaded, LLM failure) so the session is never corrupted by a failed compaction.
    """
    from agent_core.ollama_client import call_llm_chat
    from agent_core.ollama_client import get_active_model
    from agent_core.ollama_client import get_active_num_ctx

    model   = get_active_model()
    num_ctx = get_active_num_ctx()
    if not model:
        return turns, summaries

    batch     = turns[:batch_size]
    remaining = turns[batch_size:]
    batch_text = "\n\n".join(
        f"User: {t['user_prompt']}\nAssistant: {t['assistant_response']}"
        for t in batch
    )

    messages = [
        {
            "role":    "system",
            "content": (
                "You are a precise conversation summariser. "
                "Compress the following conversation exchanges into one compact paragraph. "
                "Preserve all specific facts, decisions, code, URLs, names, and conclusions reached. "
                "Write in third person (e.g. 'The user asked about X; the assistant explained Y and provided Z.'). "
                "Do not interpret, evaluate, or add information not present in the exchanges."
            ),
        },
        {
            "role":    "user",
            "content": f"Conversation to summarise:\n\n{batch_text}",
        },
    ]

    try:
        result       = call_llm_chat(model_name=model, messages=messages, tools=None, num_ctx=num_ctx)
        summary_text = (result.response or "").strip()
    except Exception:
        return turns, summaries

    if not summary_text:
        return turns, summaries

    prior_end   = summaries[-1]["turn_range"][1] if summaries else 0
    new_summary = {
        "text":       summary_text,
        "turn_range": [prior_end + 1, prior_end + len(batch)],
    }
    return remaining, summaries + [new_summary]


def _build_summary_block(summaries: list[dict]) -> str:
    """Format summary blocks into a single string for injection into the system prompt."""
    if not summaries:
        return ""
    parts = [
        f"[Turns {s['turn_range'][0]}-{s['turn_range'][1]}] {s['text']}"
        for s in summaries
    ]
    return "\n\n".join(parts)


def _save_session(
    session_id:    str,
    history:       "ConversationHistory",
    summaries:     list[dict],
    prompt_tokens: int,
    num_ctx:       int,
) -> list[dict]:
    """Persist turns and summaries to the root-level session file.

    Triggers compaction when the prompt-token fill exceeds _COMPACT_FILL_PCT of num_ctx,
    compressing the oldest half of raw turns per pass.
    Returns the (possibly updated) summaries list so the caller can inject
    fresh summaries into the next orchestration run.
    """
    turns_raw = history.as_list()
    pairs: list[dict] = []
    for i in range(0, len(turns_raw) - 1, 2):
        u = turns_raw[i]
        a = turns_raw[i + 1]
        if u.get("role") == "user" and a.get("role") == "assistant":
            pairs.append({"user_prompt": u["content"], "assistant_response": a["content"]})

    if num_ctx > 0 and pairs and prompt_tokens / num_ctx >= _COMPACT_FILL_PCT:
        batch_size  = max(1, len(pairs) // 2)
        pairs, summaries = _compact_old_turns(pairs, summaries, batch_size)

    path = _session_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"turns": pairs, "summaries": summaries}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    return summaries


@app.get("/sessions/{session_id}/history")
def get_session_history(session_id: str):
    """Return the conversation history for a session."""
    _validate_session_id(session_id)
    history, _summaries = _load_session(session_id)
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


@app.get("/logs/latest")
def get_latest_log():
    """Return the absolute path of the most recent logfile, if one exists."""
    latest = _get_latest_log_file()
    if latest is None:
        return {"path": None}
    _set_latest_log_path(latest)
    return {"path": str(latest)}


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
        with _log_subscribers_lock:
            _log_subscribers.append(subscriber)

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
            with _log_subscribers_lock:
                try:
                    _log_subscribers.remove(subscriber)
                except ValueError:
                    pass

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ====================================================================================================
# MARK: LOG BROADCAST
# ====================================================================================================
# Fan-out: each SSE client gets its own subscriber queue fed by push_log_line.
_log_subscribers:      list[queue.Queue] = []
_log_subscribers_lock: threading.Lock    = threading.Lock()


def push_log_line(line: str) -> None:
    """Push a log line to all active log-stream SSE subscribers."""
    item = {
        "type": "log",
        "text": line,
        "ts":   datetime.now().isoformat(timespec="seconds"),
        "path": _latest_log_path,
    }
    with _log_subscribers_lock:
        for sub in list(_log_subscribers):
            try:
                sub.put_nowait(item)
            except queue.Full:
                pass


def _get_log_backfill() -> list[dict]:
    """Return the last _LOG_TAIL_LINES lines from the most recent log file."""
    latest = _get_latest_log_file()
    if latest is None:
        return []
    try:
        lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()
        tail  = lines[-_LOG_TAIL_LINES:]
        _set_latest_log_path(latest)
        return [{"type": "log", "text": ln, "ts": "", "path": str(latest)} for ln in tail]
    except Exception:
        return []


def _get_latest_log_file() -> Path | None:
    if not _LOG_DIR.exists():
        return None
    day_dirs = sorted(_LOG_DIR.iterdir(), reverse=True)
    for day_dir in day_dirs:
        if not day_dir.is_dir():
            continue
        files = sorted(day_dir.glob("*.txt"), reverse=True)
        if files:
            return files[0]
    return None


# ----------------------------------------------------------------------------------------------------

@app.get("/logs/file")
def stream_log_file(path: str):
    """SSE endpoint: tail a specific log file by absolute path.

    The path must resolve inside _LOG_DIR (validated server-side to prevent traversal).
    Sends the entire existing file as backfill, then polls for new content by byte offset.
    """
    # Security: reject paths that do not resolve inside the log directory.
    try:
        requested = Path(path).resolve()
        requested.relative_to(_LOG_DIR.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Path outside log directory")

    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    def _generate():
        # Backfill: send entire existing file content first.
        try:
            content = requested.read_text(encoding="utf-8", errors="replace")
            for ln in content.splitlines():
                yield _sse({"type": "log", "text": ln, "ts": ""})
        except Exception:
            pass

        # Set byte offset AFTER backfill so the tail loop only sends genuinely new bytes.
        try:
            offset = requested.stat().st_size
        except OSError:
            offset = 0

        # Tail: poll for new bytes until shutdown or client disconnect.
        try:
            while not _shutdown_event.is_set():
                try:
                    size = requested.stat().st_size
                    if size > offset:
                        with requested.open("rb") as f:
                            f.seek(offset)
                            new_bytes = f.read()
                        offset = size
                        new_text = new_bytes.decode("utf-8", errors="replace")
                        for ln in new_text.splitlines():
                            if ln:
                                yield _sse({
                                    "type": "log",
                                    "text": ln,
                                    "ts":   datetime.now().isoformat(timespec="seconds"),
                                })
                    else:
                        yield ": keepalive\n\n"
                except OSError:
                    yield ": keepalive\n\n"
                time.sleep(_LOG_POLL_SECS)
        except GeneratorExit:
            pass

    return StreamingResponse(_generate(), media_type="text/event-stream")


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
                    # Sentinel: run finished. Clean up the queue entry now that we have
                    # consumed all events (including this sentinel).
                    with _run_queues_lock:
                        _run_event_queues.pop(run_id, None)
                    yield _sse({"type": "done", "run_id": run_id})
                    break
                yield _sse(item)
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
