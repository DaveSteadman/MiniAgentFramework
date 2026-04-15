# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Persistent prompt-history file I/O for the web UI session.
#
# Exposes load_history() and append_to_history() so the API endpoints and the web UI
# client can share a single history store (via get_chathistory_file()) without
# duplicating file-handling logic.
#
# Related modules:
#   - api.py   -- GET /history and POST /history use load_history() / append_to_history()
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import threading
from pathlib import Path

from KoreAgent.utils.workspace_utils import get_chathistory_file


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_HISTORY_FILE = get_chathistory_file()
_MAX_HISTORY  = 32    # hard cap; oldest entries are dropped when exceeded
_HISTORY_LOCK = threading.Lock()


# ====================================================================================================
# MARK: PUBLIC API
# ====================================================================================================
def load_history() -> list[str]:
    """Return the persisted history list (oldest-first)."""
    if not _HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(e) for e in data if str(e).strip()]
    except Exception:
        pass
    return []


def _save_history(entries: list[str]) -> None:
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(
            json.dumps(entries[-_MAX_HISTORY:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def append_to_history(text: str) -> None:
    """Append *text* to the persisted history file, deduplicating on full text match."""
    # Remove any existing occurrence of text (full dedup), then append so the
    # most-recent use always floats to the end. Cull to _MAX_HISTORY on save.
    text = text.strip()
    if not text:
        return
    with _HISTORY_LOCK:
        entries = load_history()
        entries = [e for e in entries if e != text]
        entries.append(text)
        _save_history(entries)
