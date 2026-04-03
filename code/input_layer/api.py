# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# FastAPI application exposing the MiniAgentFramework engine as a REST + SSE service.
#
# Endpoints:
#   GET  /                             serve static web UI (index.html)
#   GET  /version                      return framework version string
#   GET  /status/ollama                current 'ollama ps' model status
#   GET  /settings/sandbox             return current sandbox enabled state
#   POST /settings/sandbox?enabled=    set sandbox enabled state
#   GET  /completions                  tab-completion candidates (sessions, test files, tasks, models)
#   GET  /tasks                        enabled scheduled tasks with last-run and next-fire times
#   GET  /timeline                     minute-resolution task timeline centred on now
#   GET  /queue                        current task queue state
#   GET  /history                      last 20 input history entries (shared with TUI)
#   POST /history                      append an entry to input history
#   GET  /sessions/{id}/history        full conversation history for a session
#   POST /sessions/{id}/prompt         submit a new prompt (enqueues on task_queue)
#   GET  /logs                         list all log directories and files
#   GET  /logs/latest                  path of the most recently written log file
#   GET  /logs/stream                  SSE: tail all new log lines across all log files
#   GET  /logs/file?path=<path>        SSE: tail a specific log file (used for per-run view)
#   GET  /logs/{date}/{filename}       serve a specific log file
#   GET  /runs/{id}/stream             SSE: stream events for a specific enqueued run
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
#   - slash_commands.py       -- SlashCommandContext, handle; /session commands manage named sessions
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
from agent_core.ollama_client import list_ollama_models
from agent_core.orchestration import ConversationHistory
from agent_core.orchestration import OrchestratorConfig
from agent_core.orchestration import SessionContext
from agent_core.orchestration import get_sandbox_enabled
from agent_core.orchestration import orchestrate_prompt
from agent_core.orchestration import request_stop
from agent_core.orchestration import set_sandbox_enabled
from agent_core.scratchpad import scratch_clear
from input_layer.api_routes_logs import register_log_routes
from input_layer.api_routes_sessions import register_session_routes
from input_layer.api_routes_status import register_status_routes
from input_layer.api_routes_tasks import register_task_routes
from utils.runtime_logger import SessionLogger
from utils.runtime_logger import create_log_file_path
from input_layer.chat_input import append_to_history
from input_layer.chat_input import load_history
from scheduler.scheduler import is_task_due
from scheduler.scheduler import task_queue
from input_layer.slash_commands import handle as handle_slash
from input_layer.slash_command_context import SlashCommandContext
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


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    ico = _WEB_DIR / "favicon.ico"
    if not ico.exists():
        from starlette.responses import Response
        return Response(status_code=404)
    return FileResponse(str(ico), media_type="image/x-icon", headers={"Cache-Control": "no-cache"})


register_status_routes(
    app,
    get_active_host=get_active_host,
    get_active_model=get_active_model,
    get_active_num_ctx=get_active_num_ctx,
    get_ollama_ps_rows=get_ollama_ps_rows,
    version=__version__,
)


# ====================================================================================================
# MARK: COMPLETIONS ENDPOINT
# ====================================================================================================

@app.get("/completions")
def get_completions():
    """Return tab-completion candidates grouped by type for the UI tab-complete feature."""
    named_dir = get_chatsessions_named_dir()
    sessions  = []
    if named_dir.exists():
        for p in sorted(named_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                name = data.get("name", "")
                if name:
                    sessions.append(name)
            except Exception:
                pass

    test_dir   = Path(__file__).resolve().parent.parent.parent / "controldata" / "test_prompts"
    test_files = []
    if test_dir.exists():
        test_files = sorted(p.stem for p in test_dir.glob("*.json"))

    task_names = [t.get("name", "") for t in _enabled_tasks if t.get("name")]

    try:
        models = list_ollama_models()
    except Exception:
        models = []

    return {
        "sessions":   sessions,
        "test_files": test_files,
        "task_names": task_names,
        "models":     models,
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


register_task_routes(
    app,
    get_enabled_tasks=lambda: _enabled_tasks,
    get_last_run=lambda: _last_run,
    is_task_due=is_task_due,
    task_queue=task_queue,
    queue_preview_limit=_QUEUE_PREVIEW_LIMIT,
)


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


# timeline route is registered by register_task_routes()


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
# MARK: SESSION HELPERS
# ====================================================================================================
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


# ====================================================================================================
# MARK: SSE HELPER
# ====================================================================================================

def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


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


register_session_routes(
    app,
    config_getter=lambda: _config,
    validate_session_id=_validate_session_id,
    make_run_event_queue=_make_run_event_queue,
    queue_run_event=_queue_run_event,
    finish_run_event_queue=finish_run_event_queue,
    handle_stoprun_immediate=_handle_stoprun_immediate,
    load_session=_load_session,
    save_session=_save_session,
    build_summary_block=_build_summary_block,
    create_session_context=SessionContext,
    clear_session_scratch=scratch_clear,
    make_slash_context=SlashCommandContext,
    handle_slash=handle_slash,
    push_log_line=push_log_line,
    log_file_re=_LOG_FILE_RE,
    turn_agent_re=_TURN_AGENT_RE,
    turn_metrics_re=_TURN_METRICS_RE,
    test_complete_re=_TEST_COMPLETE_RE,
    set_latest_log_path=_set_latest_log_path,
    log_dir=_LOG_DIR,
    create_log_file_path=create_log_file_path,
    session_logger_cls=SessionLogger,
    orchestrate_prompt=orchestrate_prompt,
    get_active_num_ctx=get_active_num_ctx,
    task_queue=task_queue,
    run_queues=_run_event_queues,
    run_queues_lock=_run_queues_lock,
    sse=lambda data: _sse(data),
    get_chatsessions_day_dir=get_chatsessions_day_dir,
)

register_log_routes(
    app,
    log_dir=_LOG_DIR,
    shutdown_event_getter=lambda: _shutdown_event,
    log_poll_secs=_LOG_POLL_SECS,
    sse=lambda data: _sse(data),
    set_latest_log_path=_set_latest_log_path,
    get_latest_log_file=_get_latest_log_file,
    get_log_backfill=_get_log_backfill,
    log_subscribers=_log_subscribers,
    log_subscribers_lock=_log_subscribers_lock,
)
