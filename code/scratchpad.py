# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Session-scoped scratchpad store for the MiniAgentFramework.
#
# Provides a lightweight named-value store that persists for the lifetime of the process
# (i.e. one interactive session or scheduled run).  The LLM can save intermediate results
# under a short key and retrieve them later without carrying large payloads in context.
#
# Public API (used by scratchpad_skill.py and prompt_tokens.py):
#   scratch_save(key, value)  -- store a named value (overwrites on duplicate key)
#   scratch_load(key)         -- retrieve a stored value as a string
#   scratch_list()            -- return a human-readable list of current keys
#   scratch_delete(key)       -- remove one key
#   scratch_clear()           -- remove all keys (called at session reset)
#   get_store()               -- return a shallow copy of the store dict (for token resolution)
#   get_key_names()           -- return sorted list of active key names (for system prompt)
#
# Key rules:
#   - Keys are lowercased and stripped; alphanumeric plus underscore only.
#   - Values are stored as plain strings.
#   - {scratch:key} tokens in skill arguments are resolved by prompt_tokens.resolve_tokens().
#
# Related modules:
#   - code/skills/Scratchpad/scratchpad_skill.py  -- exposes these functions as tool calls
#   - code/prompt_tokens.py                       -- resolves {scratch:key} in skill args
#   - code/orchestration.py                       -- injects key names into system prompt
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_KEY_RE = re.compile(r"^[a-zA-Z0-9_]+$")


# ====================================================================================================
# MARK: STORE
# ====================================================================================================
_STORE:         dict[str, str] = {}
_DUMP_ENABLED:  bool           = False   # toggled by /scratchdump slash command


# ----------------------------------------------------------------------------------------------------
def _validate_key(key: str) -> str:
    """Normalise and validate a key; raise ValueError for illegal characters."""
    normalised = key.strip().lower()
    if not normalised:
        raise ValueError("Scratchpad key cannot be empty")
    if not _KEY_RE.match(normalised):
        raise ValueError(
            f"Scratchpad key '{key}' contains invalid characters - "
            "use letters, digits, and underscores only"
        )
    return normalised


# ====================================================================================================
# MARK: DUMP FILE CONTROL
# ====================================================================================================
def set_dump_enabled(enabled: bool) -> None:
    global _DUMP_ENABLED
    _DUMP_ENABLED = enabled


# ----------------------------------------------------------------------------------------------------
def get_dump_enabled() -> bool:
    return _DUMP_ENABLED


# ----------------------------------------------------------------------------------------------------
def _dump_path() -> Path:
    """Return the path to the persistent scratchpad dump file in controldata/."""
    from workspace_utils import get_controldata_dir  # lazy import - avoids circular at startup
    return get_controldata_dir() / "scratchpad_dump.txt"


# ----------------------------------------------------------------------------------------------------
def _flush_to_file() -> None:
    """Overwrite the dump file with the current store contents when dumping is enabled."""
    if not _DUMP_ENABLED:
        return
    path = _dump_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(scratch_dump(), encoding="utf-8")
    except Exception:
        pass   # best-effort; failures must not break the skill call


# ----------------------------------------------------------------------------------------------------
def flush_now() -> Path | None:
    """Force an immediate write to the dump file regardless of pending mutations.

    Returns the Path written to, or None when dumping is disabled.
    Used by the /scratchdump slash command to confirm the feature is active.
    """
    if not _DUMP_ENABLED:
        return None
    path = _dump_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(scratch_dump(), encoding="utf-8")
        return path
    except Exception:
        return None


# ====================================================================================================
# MARK: PUBLIC API
# ====================================================================================================
def scratch_save(key: str, value: str) -> str:
    """Store a named value in the scratchpad, overwriting any previous value for that key."""
    validated = _validate_key(key)
    _STORE[validated] = str(value)
    result = f"Saved to scratchpad key '{validated}' ({len(str(value))} chars)"
    _flush_to_file()
    return result


# ----------------------------------------------------------------------------------------------------
def scratch_load(key: str) -> str:
    """Retrieve a stored value by key.  Returns an error string when the key does not exist."""
    validated = _validate_key(key)
    if validated not in _STORE:
        return f"Scratchpad key '{validated}' not found.  Use scratch_list() to see available keys."
    return _STORE[validated]


# ----------------------------------------------------------------------------------------------------
def scratch_list() -> str:
    """Return a formatted list of all current scratchpad keys and their sizes."""
    if not _STORE:
        return "Scratchpad is empty."
    lines = []
    for key in sorted(_STORE):
        lines.append(f"  {key}  ({len(_STORE[key])} chars)")
    return "Scratchpad keys:\n" + "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def scratch_dump() -> str:
    """Return every key and its full stored value.  Intended for debugging."""
    if not _STORE:
        return "Scratchpad is empty."
    sections = []
    for key in sorted(_STORE):
        sections.append(f"[{key}]\n{_STORE[key]}")
    return "Scratchpad dump:\n\n" + "\n\n".join(sections)


# ----------------------------------------------------------------------------------------------------
def scratch_delete(key: str) -> str:
    """Remove one key from the scratchpad."""
    validated = _validate_key(key)
    if validated not in _STORE:
        return f"Scratchpad key '{validated}' not found - nothing deleted."
    del _STORE[validated]
    _flush_to_file()
    return f"Deleted scratchpad key '{validated}'."


# ----------------------------------------------------------------------------------------------------
def scratch_search(substring: str) -> str:
    """Return a list of keys whose stored value contains *substring* (case-insensitive)."""
    needle = substring.lower()
    matches = [key for key, val in _STORE.items() if needle in val.lower()]
    if not matches:
        return f"No scratchpad keys contain the substring '{substring}'."
    lines = [f"  {key}  ({len(_STORE[key])} chars)" for key in sorted(matches)]
    return f"Keys matching '{substring}':\n" + "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def scratch_clear() -> str:
    """Remove all keys from the scratchpad (called at session reset or /clear)."""
    count = len(_STORE)
    _STORE.clear()
    _flush_to_file()
    return f"Scratchpad cleared ({count} key(s) removed)."


# ====================================================================================================
# MARK: INTERNAL ACCESSORS
# ====================================================================================================
def get_store() -> dict[str, str]:
    """Return a shallow copy of the store dict.  Used by prompt_tokens for {scratch:key} resolution."""
    return dict(_STORE)


# ----------------------------------------------------------------------------------------------------
def get_key_names() -> list[str]:
    """Return a sorted list of active key names.  Used by orchestration to inject into system prompt."""
    return sorted(_STORE.keys())
