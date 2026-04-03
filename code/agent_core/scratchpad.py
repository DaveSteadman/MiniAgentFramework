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
import threading
from pathlib import Path

from agent_core.session_runtime import get_active_session_id


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_KEY_RE = re.compile(r"^[a-zA-Z0-9_]+$")


# ====================================================================================================
# MARK: STORE
# ====================================================================================================
_SESSION_STORES: dict[str, dict[str, str]] = {}
_STORE_LOCK: threading.RLock = threading.RLock()
_DUMP_ENABLED:  bool           = False   # toggled by /scratchdump slash command


def _resolve_session_id(session_id: str | None = None) -> str:
    cleaned = str(session_id or "").strip()
    return cleaned or get_active_session_id()


def _get_session_store(session_id: str | None = None) -> dict[str, str]:
    resolved = _resolve_session_id(session_id)
    with _STORE_LOCK:
        return _SESSION_STORES.setdefault(resolved, {})


# ----------------------------------------------------------------------------------------------------
def _build_scratch_query_system_prompt(instructions: str = "") -> str:
    if instructions:
        return instructions
    return (
        "You are a precise information extractor running in an isolated context. "
        "Use only the supplied content and never use outside knowledge, memory, or inference to fill gaps. "
        "Read the question and the content below, then respond with ONLY the answer:\n"
        "- If filtering a list or table: include every matching row in full, one per line. "
        "  Never group or summarise rows into ranges.\n"
        "- For requests that imply completeness such as 'list all', 'every', or 'full list', "
        "  return a complete answer only when the supplied content explicitly contains the full set.\n"
        "- Search result snippets, headlines, and summaries are not authoritative sources for exhaustive factual lists.\n"
        "- If extracting facts: pull only the directly relevant sentences, concisely.\n"
        "- If the answer is missing, partial, or cannot be proven from the supplied content, "
        "  respond with exactly: Not found in content."
    )


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
    from utils.workspace_utils import get_controldata_dir  # lazy import - avoids circular at startup
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
def scratch_save(key: str, value: str, session_id: str | None = None) -> str:
    """Store a named value in the scratchpad, overwriting any previous value for that key."""
    validated = _validate_key(key)
    store = _get_session_store(session_id)
    with _STORE_LOCK:
        store[validated] = str(value)
    result = f"Saved to scratchpad key '{validated}' ({len(str(value))} chars)"
    _flush_to_file()
    return result


# ----------------------------------------------------------------------------------------------------
def scratch_load(key: str, session_id: str | None = None) -> str:
    """Retrieve a stored value by key.  Returns an error string when the key does not exist."""
    validated = _validate_key(key)
    store = _get_session_store(session_id)
    if validated not in store:
        return f"Scratchpad key '{validated}' not found.  Use scratch_list() to see available keys."
    return store[validated]


# ----------------------------------------------------------------------------------------------------
def scratch_list(session_id: str | None = None) -> str:
    """Return a formatted list of all current scratchpad keys and their sizes."""
    store = _get_session_store(session_id)
    if not store:
        return "Scratchpad is empty."
    lines = []
    for key in sorted(store):
        lines.append(f"  {key}  ({len(store[key])} chars)")
    return "Scratchpad keys:\n" + "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def scratch_dump(session_id: str | None = None) -> str:
    """Return every key and its full stored value.  Intended for debugging."""
    store = _get_session_store(session_id)
    if not store:
        return "Scratchpad is empty."
    sections = []
    for key in sorted(store):
        sections.append(f"[{key}]\n{store[key]}")
    return "Scratchpad dump:\n\n" + "\n\n".join(sections)


# ----------------------------------------------------------------------------------------------------
def scratch_delete(key: str, session_id: str | None = None) -> str:
    """Remove one key from the scratchpad."""
    validated = _validate_key(key)
    store = _get_session_store(session_id)
    if validated not in store:
        return f"Scratchpad key '{validated}' not found - nothing deleted."
    with _STORE_LOCK:
        del store[validated]
    _flush_to_file()
    return f"Deleted scratchpad key '{validated}'."


# ----------------------------------------------------------------------------------------------------
def scratch_search(substring: str, session_id: str | None = None) -> str:
    """Return a list of keys whose stored value contains *substring* (case-insensitive)."""
    store = _get_session_store(session_id)
    needle = substring.lower()
    matches = [key for key, val in store.items() if needle in val.lower()]
    if not matches:
        return f"No scratchpad keys contain the substring '{substring}'."
    lines = [f"  {key}  ({len(store[key])} chars)" for key in sorted(matches)]
    return f"Keys matching '{substring}':\n" + "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def scratch_peek(key: str, substring: str, context_chars: int = 250, session_id: str | None = None) -> str:
    """Return the text around the first occurrence of *substring* in the value stored at *key*.

    Returns *context_chars* characters before and after the match, with '...' markers where the
    value was clipped and >>>match<<< highlighting around the hit.  Useful for inspecting a
    specific section of a large stored value without loading the entire content.
    """
    validated = _validate_key(key)
    store = _get_session_store(session_id)
    if validated not in store:
        return f"Scratchpad key '{validated}' not found. Use scratch_list() to see available keys."
    value = store[validated]
    pos   = value.lower().find(substring.lower())
    if pos == -1:
        return f"Substring '{substring}' not found in scratchpad key '{validated}'."
    context_chars = max(0, int(context_chars))
    start  = max(0, pos - context_chars)
    end    = min(len(value), pos + len(substring) + context_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(value) else ""
    match  = value[pos : pos + len(substring)]
    return (
        f"[Match in '{validated}' at char {pos} / {len(value)} total]\n"
        f"{prefix}{value[start:pos]}>>>{match}<<<{value[pos + len(substring):end]}{suffix}"
    )


# ----------------------------------------------------------------------------------------------------
def scratch_query(
    key: str,
    query: str,
    save_result_key: str = "",
    instructions: str = "",
    session_id: str | None = None,
) -> str:
    """Apply a natural-language query to stored scratchpad content via an isolated LLM call.

    Loads the full value stored at `key`, passes it to a clean-context LLM call together
    with `query`, and returns only the compact extracted answer.  The raw content never
    enters the caller's context window - this acts as a subroutine with its own stack.
    If `save_result_key` is provided the result is also saved under that key.
    """
    try:
        validated = _validate_key(key)
    except ValueError as exc:
        return f"Error: {exc}"
    store = _get_session_store(session_id)
    if validated not in store:
        return f"Scratchpad key '{validated}' not found.  Use scratch_list() to see available keys."
    if not query or not query.strip():
        return "Error: query cannot be empty."

    content = store[validated]

    # Lazy imports to avoid circular deps at module load time.
    # Must use the fully-qualified package path so we share the same module
    # object (and the same _active_model global) as the rest of the app.
    # A bare 'from ollama_client import' would create a second independent
    # module instance (sys.modules["ollama_client"] != sys.modules["agent_core.ollama_client"])
    # because code/agent_core/ can end up on sys.path via scratchpad_skill.py.
    try:
        from agent_core.ollama_client import call_llm_chat as _call_llm_chat
        from agent_core.ollama_client import get_active_model as _get_active_model
        from agent_core.ollama_client import get_active_num_ctx as _get_active_num_ctx
    except Exception as exc:
        return f"Error importing LLM client: {exc}"

    model   = _get_active_model()
    num_ctx = _get_active_num_ctx()
    query_lower = query.lower()
    content_lower = content.lower()
    if (
        not model
        and any(token in query_lower for token in ("list all", "every", "full list", "complete list"))
        and ("search results for:" in content_lower or "https://" in content_lower)
    ):
        return "Not found in content."
    if not model:
        return "Error: no active model available.  Run a prompt first."

    inner_messages = [
        {
            "role":    "system",
            "content": _build_scratch_query_system_prompt(instructions),
        },
        {
            "role":    "user",
            "content": f"Question: {query}\n\nContent:\n{content}",
        },
    ]

    try:
        result    = _call_llm_chat(model_name=model, messages=inner_messages, tools=None, num_ctx=num_ctx)
        extracted = (result.response or "").strip()
        if not extracted:
            return f"LLM returned an empty response for query on key '{validated}'."
        if save_result_key:
            try:
                validated_save = _validate_key(save_result_key)
            except ValueError as exc:
                return f"Error in save_result_key: {exc}"
            with _STORE_LOCK:
                store[validated_save] = extracted
            _flush_to_file()
            return f"[Result saved to '{validated_save}']\n{extracted}"
        return extracted
    except Exception as exc:
        return f"Error during isolated LLM query: {exc}"


# ----------------------------------------------------------------------------------------------------
def scratch_clear(session_id: str | None = None) -> str:
    """Remove all keys from the scratchpad (called at session reset or /clear)."""
    resolved = _resolve_session_id(session_id)
    store = _get_session_store(resolved)
    count = len(store)
    with _STORE_LOCK:
        _SESSION_STORES[resolved] = {}
    _flush_to_file()
    return f"Scratchpad cleared ({count} key(s) removed)."


# ====================================================================================================
# MARK: INTERNAL ACCESSORS
# ====================================================================================================
def get_store(session_id: str | None = None) -> dict[str, str]:
    """Return a shallow copy of the store dict.  Used by prompt_tokens for {scratch:key} resolution."""
    return dict(_get_session_store(session_id))


# ----------------------------------------------------------------------------------------------------
def get_key_names(session_id: str | None = None) -> list[str]:
    """Return a sorted list of active key names.  Used by orchestration to inject into system prompt."""
    return sorted(_get_session_store(session_id).keys())
