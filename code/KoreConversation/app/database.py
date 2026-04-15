# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# SQLite data-access layer for KoreConversation.
#
# Each public function creates its own connection so it is safe to call from any thread.
# WAL mode is enabled so readers and writers can overlap without blocking.
#
# Schema summary:
#   conversations  - canonical conversation record (summary, scratchpad, profile, status)
#   messages       - append-only exchange log (inbound/outbound, summarised flag)
#   events         - coordination queue between MiniAgentFramework and KoreComms
#                    (atomic claim via BEGIN IMMEDIATE prevents double-pickup)
#
# Claim timeout reaper:
#   release_stale_claims() resets events claimed longer ago than CLAIM_TIMEOUT_SECS.
#   Called from the background reaper thread started in api.py lifespan.
# ====================================================================================================

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Generator

from app.config import cfg

# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================

CLAIM_TIMEOUT_SECS = 600  # 10 minutes

_PROFILE_DEFAULTS: dict[str, str] = {
    "webchat": "admin",
}
_FALLBACK_PROFILE = "external"

_DB_PATH: Path | None = None


# ====================================================================================================
# MARK: CONNECTION
# ====================================================================================================

def get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = Path(cfg["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = data_dir / "koreconversation.db"
    return _DB_PATH


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    c = sqlite3.connect(get_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ====================================================================================================
# MARK: SCHEMA
# ====================================================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_type        TEXT    NOT NULL DEFAULT 'webchat',
    profile             TEXT    NOT NULL DEFAULT 'admin'
                                CHECK(profile IN ('admin','external','readonly')),
    status              TEXT    NOT NULL DEFAULT 'active'
                                CHECK(status IN ('active','waiting_agent','agent_processing','archived','deleted')),
    subject             TEXT,
    external_id         TEXT,
    thread_summary      TEXT    NOT NULL DEFAULT '',
    scratchpad          TEXT    NOT NULL DEFAULT '{}',
    background_context  TEXT    NOT NULL DEFAULT '',
    token_estimate      INTEGER NOT NULL DEFAULT 0,
    turn_count          INTEGER NOT NULL DEFAULT 0,
    last_activity_at    TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction        TEXT    NOT NULL CHECK(direction IN ('inbound','outbound')),
    content          TEXT    NOT NULL,
    sender_display   TEXT    NOT NULL DEFAULT '',
    status           TEXT    NOT NULL DEFAULT 'received'
                             CHECK(status IN ('received','draft','sent','failed')),
    summarised       INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    event_type       TEXT    NOT NULL
                             CHECK(event_type IN (
                                 'response_needed','outbound_ready','compress_needed',
                                 'conversation_closed','conversation_deleted'
                             )),
    status           TEXT    NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','claimed','completed','failed')),
    claimed_by       TEXT,
    claimed_at       TEXT,
    priority         INTEGER NOT NULL DEFAULT 0,
    payload          TEXT    NOT NULL DEFAULT '{}',
    created_at       TEXT    NOT NULL,
    completed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conv       ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_summarised ON messages(conversation_id, summarised);
CREATE INDEX IF NOT EXISTS idx_events_status       ON events(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_events_conv         ON events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_convs_status        ON conversations(status, last_activity_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_convs_external_id ON conversations(external_id)
    WHERE external_id IS NOT NULL;
"""


# ----------------------------------------------------------------------------------------------------
def init_db() -> None:
    with _conn() as c:
        # Migration first: add external_id before executescript so the unique
        # index on that column (defined in _SCHEMA) can be created successfully.
        cols = {row[1] for row in c.execute("PRAGMA table_info(conversations)")}
        if cols and "external_id" not in cols:
            c.execute("ALTER TABLE conversations ADD COLUMN external_id TEXT")
        c.executescript(_SCHEMA)


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _default_profile(channel_type: str) -> str:
    return _PROFILE_DEFAULTS.get(channel_type, _FALLBACK_PROFILE)


# ====================================================================================================
# MARK: CONVERSATIONS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def conversation_create(
    channel_type:       str,
    subject:            str | None = None,
    background_context: str        = "",
    profile:            str | None = None,
    external_id:        str | None = None,
) -> dict:
    now     = _now()
    profile = profile or _default_profile(channel_type)
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO conversations
                (channel_type, profile, status, subject, external_id, thread_summary, scratchpad,
                 background_context, token_estimate, turn_count,
                 last_activity_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (channel_type, profile, "active", subject, external_id, "", "{}", background_context, 0, 0, now, now, now),
        )
        row_id = cur.lastrowid
    return conversation_get(row_id)


# ----------------------------------------------------------------------------------------------------
def conversation_get_by_external_id(external_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE external_id = ? LIMIT 1", (external_id,)
        ).fetchone()
    if row is None:
        return None
    result               = _row_to_dict(row)
    result["scratchpad"] = json.loads(result["scratchpad"] or "{}")
    return result


# ----------------------------------------------------------------------------------------------------
def conversation_get(conversation_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    if row is None:
        return None
    result              = _row_to_dict(row)
    result["scratchpad"] = json.loads(result["scratchpad"] or "{}")
    return result


# ----------------------------------------------------------------------------------------------------
def conversation_get_with_messages(conversation_id: int) -> dict | None:
    conv = conversation_get(conversation_id)
    if conv is None:
        return None
    with _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND summarised = 0
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
    conv["messages"] = [_row_to_dict(r) for r in rows]
    return conv


# ----------------------------------------------------------------------------------------------------
def conversation_list(
    status:       str | None = None,
    channel_type: str | None = None,
    limit:        int        = 50,
    offset:       int        = 0,
) -> list[dict]:
    query  = "SELECT * FROM conversations WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if channel_type:
        query += " AND channel_type = ?"
        params.append(channel_type)
    query += " ORDER BY last_activity_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    result = []
    for row in rows:
        item               = _row_to_dict(row)
        item["scratchpad"] = json.loads(item["scratchpad"] or "{}")
        result.append(item)
    return result


# ----------------------------------------------------------------------------------------------------
def conversation_update(
    conversation_id: int,
    status:           str | None  = None,
    thread_summary:   str | None  = None,
    scratchpad:       dict | None = None,
    background_context: str | None = None,
    token_estimate:   int | None  = None,
    turn_count:       int | None  = None,
) -> dict | None:
    now    = _now()
    fields = ["updated_at = ?", "last_activity_at = ?"]
    params = [now, now]
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if thread_summary is not None:
        fields.append("thread_summary = ?")
        params.append(thread_summary)
    if scratchpad is not None:
        fields.append("scratchpad = ?")
        params.append(json.dumps(scratchpad))
    if background_context is not None:
        fields.append("background_context = ?")
        params.append(background_context)
    if token_estimate is not None:
        fields.append("token_estimate = ?")
        params.append(token_estimate)
    if turn_count is not None:
        fields.append("turn_count = ?")
        params.append(turn_count)
    params.append(conversation_id)
    with _conn() as c:
        c.execute(
            f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?",
            params,
        )
    return conversation_get(conversation_id)


# ----------------------------------------------------------------------------------------------------
def conversation_delete(conversation_id: int) -> bool:
    conversation_update(conversation_id, status="deleted")
    event_create(conversation_id, "conversation_deleted")
    return True


# ====================================================================================================
# MARK: MESSAGES
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def message_append(
    conversation_id: int,
    direction:       str,
    content:         str,
    sender_display:  str = "",
    status:          str = "received",
) -> dict:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO messages (conversation_id, direction, content, sender_display, status, summarised, created_at)
            VALUES (?,?,?,?,?,0,?)
            """,
            (conversation_id, direction, content, sender_display, status, now),
        )
        row_id = cur.lastrowid
        row    = c.execute("SELECT * FROM messages WHERE id = ?", (row_id,)).fetchone()
    return _row_to_dict(row)


# ----------------------------------------------------------------------------------------------------
def message_list(
    conversation_id: int,
    summarised:      int | None = None,
    direction:       str | None = None,
    limit:           int        = 200,
) -> list[dict]:
    query  = "SELECT * FROM messages WHERE conversation_id = ?"
    params: list = [conversation_id]
    if summarised is not None:
        query += " AND summarised = ?"
        params.append(summarised)
    if direction:
        query += " AND direction = ?"
        params.append(direction)
    query += " ORDER BY created_at ASC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# ----------------------------------------------------------------------------------------------------
def message_update(
    message_id: int,
    status:     str | None = None,
    summarised: int | None = None,
) -> dict | None:
    fields = []
    params: list = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if summarised is not None:
        fields.append("summarised = ?")
        params.append(summarised)
    if not fields:
        return None
    params.append(message_id)
    with _conn() as c:
        c.execute(f"UPDATE messages SET {', '.join(fields)} WHERE id = ?", params)
        row = c.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return _row_to_dict(row) if row else None


# ====================================================================================================
# MARK: EVENTS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def event_create(
    conversation_id: int | None,
    event_type:      str,
    priority:        int  = 0,
    payload:         dict | None = None,
) -> dict:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO events (conversation_id, event_type, status, priority, payload, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                conversation_id,
                event_type,
                "pending",
                priority,
                json.dumps(payload or {}),
                now,
            ),
        )
        row_id = cur.lastrowid
        row    = c.execute("SELECT * FROM events WHERE id = ?", (row_id,)).fetchone()
    return _row_to_dict(row)


# ----------------------------------------------------------------------------------------------------
def event_claim_next(claimed_by: str) -> dict | None:
    """Atomically claim the highest-priority pending event. Returns the event dict or None."""
    now = _now()
    with _conn() as c:
        # BEGIN IMMEDIATE gives write lock for the duration - prevents double-claim.
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            """
            SELECT * FROM events
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            c.execute("COMMIT")
            return None
        event_id = row["id"]
        c.execute(
            "UPDATE events SET status='claimed', claimed_by=?, claimed_at=? WHERE id=?",
            (claimed_by, now, event_id),
        )
        c.execute("COMMIT")
        updated = c.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_dict(updated)


# ----------------------------------------------------------------------------------------------------
def event_complete(event_id: int, status: str = "completed") -> dict | None:
    now = _now()
    with _conn() as c:
        c.execute(
            "UPDATE events SET status=?, completed_at=? WHERE id=?",
            (status, now, event_id),
        )
        row = c.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_dict(row) if row else None


# ----------------------------------------------------------------------------------------------------
def release_stale_claims() -> int:
    """Reset claimed events that have been held beyond CLAIM_TIMEOUT_SECS. Returns count released."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TIMEOUT_SECS)
    cutoff_str = cutoff.isoformat()
    with _conn() as c:
        cur = c.execute(
            "UPDATE events SET status='pending', claimed_by=NULL, claimed_at=NULL "
            "WHERE status='claimed' AND claimed_at < ?",
            (cutoff_str,),
        )
        return cur.rowcount


# ----------------------------------------------------------------------------------------------------
def event_list(
    conversation_id: int | None = None,
    status:          str | None = None,
    limit:           int        = 200,
) -> list[dict]:
    clauses: list[str] = []
    params:  list      = []
    if conversation_id is not None:
        clauses.append("conversation_id = ?")
        params.append(conversation_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ----------------------------------------------------------------------------------------------------
def event_counts() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) as n FROM events GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}


# ----------------------------------------------------------------------------------------------------
def conversation_counts() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) as n FROM conversations GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}
