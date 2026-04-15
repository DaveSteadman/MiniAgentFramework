# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# KoreConversation input source for MiniAgentFramework.
#
# Runs as a background polling thread (started by api_mode.py) that calls
# GET /events/next?claimed_by=agent on KoreConversation. Each claimed event delivers
# a conversation record with its full message list. The agent builds a prompt from the
# conversation, runs orchestration, then writes the reply back as an outbound message,
# patches conversation state, and marks the event complete.
#
# Conversation lifecycle per run:
#   1. Claim event (GET /events/next) - returns event + full conversation
#   2. Build prompt from thread_summary + unsummarised messages + scratchpad
#   3. Run orchestrate_prompt
#   4. POST /conversations/{id}/messages  (outbound reply)
#   5. PATCH /conversations/{id}          (updated thread_summary, scratchpad, token_estimate, turn_count)
#   6. POST /events/{event_id}/complete   {status: "completed"}
#   7. POST /events                       {event_type: "outbound_ready"}  (for KoreComms if needed)
#
# Each conversation maps to a stable session_id "kc_conv_{id}" for orchestration history.
#
# Configuration:
#   "koreconvurl" in default.json (repo root), e.g. "http://localhost:8700".
#   If absent, the thread exits immediately with a notice.
#
# Public entry point:
#   start_koreconv_loop(config, push_log_line, task_queue, create_log_file_path,
#                       log_dir, session_logger_cls, shutdown)
#
# Related modules:
#   - api_mode.py          -- calls start_koreconv_loop alongside _scheduler_loop
#   - scheduler.py         -- task_queue singleton used for serialisation
#   - orchestration.py     -- orchestrate_prompt, OrchestratorConfig
#   - run_helpers.py       -- make_task_session
#   - koreconv_client.py   -- process lifecycle (start/stop); not used here for HTTP
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from KoreAgent.orchestration import OrchestratorConfig
from KoreAgent.orchestration import orchestrate_prompt
from KoreAgent.run_helpers import make_task_session
from KoreAgent.scratchpad import get_store
from KoreAgent.scratchpad import scratch_clear
from KoreAgent.scratchpad import scratch_save
from KoreAgent.utils.runtime_logger import SessionLogger
from KoreAgent.utils.workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DEFAULTS_PATH     = get_workspace_root() / "default.json"
_CONFIG_KEY        = "koreconvurl"
_DEFAULT_POLL_SECS = 3
_DEFAULT_TIMEOUT   = 8
_SESSION_PREFIX    = "kc_conv_"


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _get_base_url() -> str | None:
    try:
        raw = _DEFAULTS_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)
        url = cfg.get(_CONFIG_KEY, "").strip().rstrip("/")
        return url if url else None
    except Exception:
        return None


# ====================================================================================================
# MARK: HTTP HELPERS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _http_get(base: str, path: str, timeout: int = _DEFAULT_TIMEOUT) -> dict | None:
    url = f"{base}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 204:
                return None
            raw = resp.read().decode("utf-8").strip()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        raise RuntimeError(f"KC HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:120]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"KC unreachable: {exc.reason}") from exc


# ----------------------------------------------------------------------------------------------------
def _http_post(base: str, path: str, payload: dict, timeout: int = _DEFAULT_TIMEOUT) -> dict | None:
    url  = f"{base}{path}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data    = body,
        headers = {"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"KC HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:120]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"KC unreachable: {exc.reason}") from exc


# ----------------------------------------------------------------------------------------------------
def _http_patch(base: str, path: str, payload: dict, timeout: int = _DEFAULT_TIMEOUT) -> dict | None:
    url  = f"{base}{path}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data    = body,
        method  = "PATCH",
        headers = {"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"KC HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:120]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"KC unreachable: {exc.reason}") from exc


# ====================================================================================================
# MARK: PROMPT BUILDER
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _build_prompt(conv: dict, messages: list[dict]) -> str:
    """Build an LLM user prompt from a KoreConversation conversation record and its messages."""
    thread_summary    = (conv.get("thread_summary") or "").strip()
    background        = (conv.get("background_context") or "").strip()
    scratchpad        = conv.get("scratchpad") or {}
    if isinstance(scratchpad, str):
        try:
            scratchpad = json.loads(scratchpad)
        except Exception:
            scratchpad = {}

    channel  = conv.get("channel_type", "unknown")
    conv_id  = conv.get("id", "?")
    subject  = (conv.get("subject") or "").strip()

    # Unsummarised messages only - summarised ones are already in thread_summary.
    unsummarised = [m for m in messages if not m.get("summarised")]

    parts: list[str] = []

    if background:
        parts.append(f"--- Background context ---\n{background}")

    if thread_summary:
        parts.append(f"--- Prior conversation summary ---\n{thread_summary}")

    if scratchpad:
        kv = "\n".join(f"  {k}: {v}" for k, v in scratchpad.items())
        parts.append(f"--- Scratchpad ---\n{kv}")

    if unsummarised:
        lines: list[str] = []
        for m in unsummarised:
            direction = m.get("direction", "?")
            sender    = (m.get("sender_display") or "").strip()
            content   = (m.get("content") or "").strip()
            ts        = (m.get("created_at") or "")[:16]
            if direction == "inbound":
                label = f"User ({sender})" if sender else "User"
            else:
                label = "Agent"
            lines.append(f"[{ts}] {label}: {content}")
        parts.append("--- Conversation ---\n" + "\n\n".join(lines))

    header = f"You are handling a conversation (id={conv_id}, channel={channel}"
    if subject:
        header += f", subject: {subject}"
    header += ")."
    parts.insert(0, header)

    # The last inbound message is the one to respond to.
    last_inbound = next(
        (m for m in reversed(unsummarised) if m.get("direction") == "inbound"),
        None,
    )
    if last_inbound:
        content = (last_inbound.get("content") or "").strip()
        parts.append(f"--- Respond to this message ---\n{content}")

    return "\n\n".join(parts)


# ====================================================================================================
# MARK: EVENT HANDLER
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _handle_event(
    event:               dict,
    config:              OrchestratorConfig,
    log_dir:             Path,
    session_logger_cls,
    create_log_file_path,
    push_log_line,
) -> None:
    """Full lifecycle for one KoreConversation response_needed event."""
    base    = _get_base_url()
    if not base:
        return

    event_id = event.get("id")
    conv     = event.get("conversation") or {}
    conv_id  = conv.get("id")

    if not conv_id:
        push_log_line(f"[KORECONV] Event {event_id} has no conversation - completing as failed")
        try:
            _http_post(base, f"/events/{event_id}/complete", {"status": "failed"})
        except Exception:
            pass
        return

    session_id   = f"{_SESSION_PREFIX}{conv_id}"
    turn_count   = conv.get("turn_count", 0)
    push_log_line(f"[KORECONV] Handling event {event_id} (conv {conv_id}, turn {turn_count + 1})")

    run_log_path = create_log_file_path(log_dir=log_dir)
    with session_logger_cls(run_log_path) as run_logger:

        # The event payload already includes unsummarised messages (from conversation_get_with_messages).
        # Use those directly; fall back to a separate HTTP call if the field is absent.
        messages = conv.get("messages")
        if messages is None:
            try:
                messages = _http_get(base, f"/conversations/{conv_id}/messages?limit=500") or []
            except Exception as exc:
                push_log_line(f"[KORECONV] Conv {conv_id}: could not fetch messages: {exc}")
                messages = []

        # Restore persisted scratchpad state into the active session before orchestration
        # so scratchpad tool calls operate on the KC-backed conversation state.
        conv_scratchpad = conv.get("scratchpad") or {}
        if isinstance(conv_scratchpad, str):
            try:
                conv_scratchpad = json.loads(conv_scratchpad)
            except Exception:
                conv_scratchpad = {}
        scratch_clear(session_id=session_id)
        for scratch_key, scratch_value in conv_scratchpad.items():
            try:
                scratch_save(scratch_key, str(scratch_value), session_id=session_id)
            except Exception:
                pass

        user_prompt = _build_prompt(conv, messages)

        # KC owns the persisted conversation state. The agent keeps only transient
        # per-run session context in memory for this turn.
        _, session_ctx = make_task_session(
            session_id   = session_id,
            persist_path = None,
            max_turns    = 10,
        )

        response, prompt_tokens, _ct, ok, tps = orchestrate_prompt(
            user_prompt          = user_prompt,
            config               = config,
            logger               = run_logger,
            conversation_history = None,
            session_context      = session_ctx,
            quiet                = True,
        )

        tps_str = f"{tps:.1f}" if tps > 0 else "0"
        push_log_line(
            f"[KORECONV] Conv {conv_id}: [{prompt_tokens:,} tok, {tps_str} tok/s, ok={ok}]"
        )

        reply = response.strip()
        current_scratchpad = get_store(session_id=session_id)

        # Write outbound message
        try:
            _http_post(base, f"/conversations/{conv_id}/messages", {
                "direction":      "outbound",
                "content":        reply,
                "sender_display": "agent",
                "status":         "sent",
            })
        except Exception as exc:
            push_log_line(f"[KORECONV] Conv {conv_id}: failed to write outbound message: {exc}")

        # Patch conversation metadata
        try:
            _http_patch(base, f"/conversations/{conv_id}", {
                "status":         "waiting_agent",
                "token_estimate": prompt_tokens,
                "turn_count":     turn_count + 1,
                "scratchpad":     current_scratchpad,
            })
        except Exception as exc:
            push_log_line(f"[KORECONV] Conv {conv_id}: failed to patch conversation: {exc}")

        # Complete the event
        try:
            _http_post(base, f"/events/{event_id}/complete", {"status": "completed"})
        except Exception as exc:
            push_log_line(f"[KORECONV] Event {event_id}: complete failed: {exc}")

        # Raise outbound_ready for KoreComms delivery if needed
        channel = conv.get("channel_type", "webchat")
        if channel != "webchat":
            try:
                _http_post(base, "/events", {
                    "conversation_id": conv_id,
                    "event_type":      "outbound_ready",
                    "priority":        0,
                    "payload":         {},
                })
            except Exception as exc:
                push_log_line(f"[KORECONV] Conv {conv_id}: outbound_ready event failed: {exc}")


# ====================================================================================================
# MARK: BACKGROUND LOOP
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def start_koreconv_loop(
    config:              OrchestratorConfig,
    push_log_line,
    task_queue,
    create_log_file_path,
    log_dir:             Path,
    session_logger_cls,
    shutdown:            threading.Event,
) -> threading.Thread:
    """Start the background KoreConversation polling thread and return it.

    Polls GET /events/next?claimed_by=agent every _DEFAULT_POLL_SECS seconds.
    Each claimed event is enqueued into task_queue so LLM work runs serially.
    If koreconvurl is not configured, the thread exits immediately.
    """
    def _loop() -> None:
        base = _get_base_url()
        if not base:
            push_log_line("[KORECONV] koreconvurl not configured - KoreConversation integration disabled.")
            return

        push_log_line(f"[KORECONV] Polling {base} every {_DEFAULT_POLL_SECS}s")

        while not shutdown.is_set():
            try:
                event = _http_get(base, "/events/next?claimed_by=agent")
                if event is not None:
                    event_id  = event.get("id")
                    conv_id   = (event.get("conversation") or {}).get("id", "?")
                    task_name = f"kc_event_{event_id}"

                    def _run_event(_ev=event) -> None:
                        _handle_event(
                            event                = _ev,
                            config               = config,
                            log_dir              = log_dir,
                            session_logger_cls   = session_logger_cls,
                            create_log_file_path = create_log_file_path,
                            push_log_line        = push_log_line,
                        )

                    queued = task_queue.enqueue(task_name, "koreconv", _run_event)
                    if queued:
                        push_log_line(f"[KORECONV] Event {event_id} (conv {conv_id}) queued as '{task_name}'")
                    else:
                        push_log_line(f"[KORECONV] Event {event_id} (conv {conv_id}) already in task queue - skipping")

            except Exception as exc:
                push_log_line(f"[KORECONV] Poll error: {exc}")

            # Short-burst sleep so shutdown is responsive.
            for _ in range(_DEFAULT_POLL_SECS * 2):
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    thread = threading.Thread(target=_loop, daemon=True, name="koreconv-poller")
    thread.start()
    return thread
