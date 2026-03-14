# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Persistent-history input helper for CLI chat mode.
#
# Provides prompt_with_history(): a drop-in replacement for input() that gives the user
# up/down arrow navigation through their full prompt history.  History is persisted to
# controldata/chathistory.json so it survives across runs and sessions.
#
# Also exposes load_history() and append_to_history() so the dashboard TextEdit widget
# can share the same history store without duplicating file-handling logic.
#
# Uses prompt_toolkit when available (installed on first use via requirements.txt).
# Falls back silently to plain input() if prompt_toolkit is not installed, so the rest
# of the application continues to work without it.
#
# Related modules:
#   - main.py            -- calls prompt_with_history() inside run_chat_mode()
#   - modes/dashboard.py -- calls load_history() / append_to_history() for the TUI input bar
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
from pathlib import Path

from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_HISTORY_FILE = get_workspace_root() / "controldata" / "chathistory.json"
_MAX_HISTORY  = 500   # cap to avoid unbounded growth


# ====================================================================================================
# MARK: HISTORY FILE I/O
# ====================================================================================================
def _load_history() -> list[str]:
    """Load history entries from the JSON file; return empty list on any error."""
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


def _append_to_history(text: str) -> None:
    """Load the current file, append *text* (deduplicating consecutive duplicates), save."""
    text = text.strip()
    if not text:
        return
    entries = _load_history()
    if not entries or entries[-1] != text:
        entries.append(text)
    _save_history(entries)


# ====================================================================================================
# MARK: PUBLIC API
# ====================================================================================================
def load_history() -> list[str]:
    """Return the persisted history list (oldest-first) for callers outside this module."""
    return _load_history()


def append_to_history(text: str) -> None:
    """Append *text* to the persisted history file (deduplicating consecutive duplicates)."""
    _append_to_history(text)


def prompt_with_history(prompt_text: str = "You: ") -> str:
    """Display *prompt_text* and return the user's input, with up/down arrow history.

    The returned string is already stripped.  An EOFError or KeyboardInterrupt is re-raised
    so callers can handle session termination exactly as they would with plain input().

    If prompt_toolkit is not installed, falls back to plain input() - history file is still
    updated so it is ready when prompt_toolkit becomes available.
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory

        # Build an InMemoryHistory pre-loaded with the persisted entries.
        # prompt_toolkit expects oldest-first; the user navigates with the up arrow
        # from the most recent entry backwards.
        pt_history = InMemoryHistory()
        for entry in _load_history():
            pt_history.append_string(entry)

        session: PromptSession = PromptSession(history=pt_history)
        text = session.prompt(prompt_text).strip()

    except ImportError:
        # Graceful degradation: plain input().
        text = input(prompt_text).strip()

    if text:
        _append_to_history(text)

    return text
