# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# FileAccess skill module for the MiniAgentFramework.
#
# Provides safe file read/write/append operations constrained to the workspace root, with sensible
# defaults for relative paths.
#
# Path behavior:
#   - bare file name or relative path resolves under data/
#   - path starting with "./" resolves from workspace root (but still must be inside data/)
#   - absolute paths are allowed only when they resolve inside the data/ directory
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import csv
import io
from pathlib import Path

from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
WORKSPACE_ROOT   = get_workspace_root()
DEFAULT_DATA_DIR = WORKSPACE_ROOT / "data"



# ====================================================================================================
# MARK: PATH SAFETY
# ====================================================================================================
def _ensure_data_dir() -> None:
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------------------------------
def _sanitize_input_path(file_path: str) -> str:
    cleaned = str(file_path or "").strip().strip('"').strip("'")
    if not cleaned:
        raise ValueError("file_path cannot be empty")
    return cleaned.replace("\\", "/")


# ----------------------------------------------------------------------------------------------------
def _resolve_safe_path(file_path: str) -> Path:
    _ensure_data_dir()
    normalized = _sanitize_input_path(file_path)

    if normalized.startswith("./"):
        candidate = (WORKSPACE_ROOT / normalized[2:]).resolve()
    else:
        candidate_path = Path(normalized)
        if candidate_path.is_absolute():
            candidate = candidate_path.resolve()
        else:
            # Both bare names and multi-segment relative paths resolve under data/.
            # Use "./" prefix to anchor a path at workspace root instead.
            candidate = (DEFAULT_DATA_DIR / normalized).resolve()

    try:
        candidate.relative_to(DEFAULT_DATA_DIR)
    except ValueError as path_error:
        raise ValueError(f"Path escapes data directory and is not allowed: {file_path}") from path_error

    return candidate


# ----------------------------------------------------------------------------------------------------
def _parse_system_info_pairs(text: str) -> list[tuple[str, str]] | None:
    stripped = str(text or "").strip()
    if not stripped.lower().startswith("system info:"):
        return None

    payload = stripped.split(":", maxsplit=1)[1].strip()
    if not payload:
        return None

    pairs: list[tuple[str, str]] = []
    for segment in payload.split(";"):
        entry = segment.strip()
        if not entry or "=" not in entry:
            return None

        key, value = entry.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key:
            return None
        pairs.append((key, value))

    return pairs or None


# ----------------------------------------------------------------------------------------------------
def _coerce_text_for_target(target_path: Path, text: str) -> str:
    text_value = str(text)

    if target_path.suffix.lower() != ".csv":
        return text_value

    system_info_pairs = _parse_system_info_pairs(text_value)
    if not system_info_pairs:
        return text_value

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(["key", "value"])
    for key, value in system_info_pairs:
        writer.writerow([key, value])
    return csv_buffer.getvalue()


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def write_file(path: str, content: str) -> str:
    try:
        target_path = _resolve_safe_path(path)
    except ValueError as err:
        return f"Error: {err}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(_coerce_text_for_target(target_path=target_path, text=content), encoding="utf-8")
    return f"Wrote {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def append_file(path: str, content: str) -> str:
    try:
        target_path = _resolve_safe_path(path)
    except ValueError as err:
        return f"Error: {err}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    text_to_write = str(content).replace("\\n", "\n")  # unescape literal \n from model output
    if not text_to_write.endswith("\n"):
        text_to_write += "\n"
    with target_path.open("a", encoding="utf-8") as output_file:
        output_file.write(text_to_write)
    return f"Appended {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def read_file(path: str, max_chars: int = 8000) -> str:
    try:
        target_path = _resolve_safe_path(path)
    except ValueError as err:
        return f"Error: {err}"
    if not target_path.exists():
        return f"File not found: {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"

    content = target_path.read_text(encoding="utf-8")
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n[truncated]"


# ----------------------------------------------------------------------------------------------------
def find_files(keywords: list[str], search_root: str = "") -> str:
    """Search the workspace for files whose name contains all of the given keyword fragments.

    Returns a newline-separated list of matching workspace-relative paths.
    Pass an empty list (or omit keywords) to list all files.
    Pass search_root (e.g. 'data') to restrict the search to a subdirectory.
    """
    keywords_clean = [str(k).strip().lower() for k in (keywords or []) if str(k).strip()]

    if search_root and search_root.strip() not in (".", ""):
        try:
            base = _resolve_safe_path(search_root if "/" in search_root else search_root + "/placeholder")
            base = base.parent if base.suffix else base
        except ValueError:
            return f"Error: search_root '{search_root}' escapes workspace."
    else:
        base = DEFAULT_DATA_DIR

    matches = [
        p.relative_to(WORKSPACE_ROOT).as_posix()
        for p in sorted(base.rglob("*"))
        if p.is_file()
        and (not keywords_clean or all(k in p.name.lower() for k in keywords_clean))
    ]

    label = ", ".join(f"'{k}'" for k in keywords_clean)
    if not matches:
        return (
            f"No files found matching all of {label}" + (f" under {search_root}" if search_root else "") + "."
            if keywords_clean
            else "No files found" + (f" under {search_root}" if search_root else "") + "."
        )
    return "\n".join(matches)


# ----------------------------------------------------------------------------------------------------
def find_folders(keywords: list[str], search_root: str = "") -> str:
    """Search the workspace for folders whose name contains all of the given keyword fragments.

    Returns a newline-separated list of matching workspace-relative paths.
    Pass an empty list (or omit keywords) to list all folders.
    Pass search_root (e.g. 'data') to restrict the search to a subdirectory.
    """
    keywords_clean = [str(k).strip().lower() for k in (keywords or []) if str(k).strip()]

    if search_root and search_root.strip() not in (".", ""):
        try:
            base = _resolve_safe_path(search_root if "/" in search_root else search_root + "/placeholder")
            base = base.parent if base.suffix else base
        except ValueError:
            return f"Error: search_root '{search_root}' escapes workspace."
    else:
        base = DEFAULT_DATA_DIR

    matches = [
        p.relative_to(WORKSPACE_ROOT).as_posix()
        for p in sorted(base.rglob("*"))
        if p.is_dir()
        and (not keywords_clean or all(k in p.name.lower() for k in keywords_clean))
    ]

    label = ", ".join(f"'{k}'" for k in keywords_clean)
    if not matches:
        return (
            f"No folders found matching all of {label}" + (f" under {search_root}" if search_root else "") + "."
            if keywords_clean
            else "No folders found" + (f" under {search_root}" if search_root else "") + "."
        )
    return "\n".join(matches)


# ----------------------------------------------------------------------------------------------------
def create_folder(path: str) -> str:
    """Create a directory (and any missing parents) at the given workspace-relative path.

    Safe to call when the directory already exists - returns a success message either way.
    """
    try:
        # Append a dummy leaf so _resolve_safe_path can validate the path, then take the parent.
        folder = _resolve_safe_path(path.rstrip("/") + "/.keep").parent
    except ValueError as err:
        return f"Error: {err}"
    existed = folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    rel = folder.relative_to(WORKSPACE_ROOT).as_posix()
    return f"Folder already exists: {rel}" if existed else f"Created folder: {rel}"


# ----------------------------------------------------------------------------------------------------
def folder_exists(path: str) -> str:
    """Return whether a directory exists at the given workspace-relative path.

    Returns 'yes' or 'no' so the model can branch on the result directly.
    """
    try:
        folder = _resolve_safe_path(path.rstrip("/") + "/.keep").parent
    except ValueError as err:
        return f"Error: {err}"
    return "yes" if folder.exists() and folder.is_dir() else "no"


# ----------------------------------------------------------------------------------------------------
def write_from_scratch(scratch_key: str, path: str) -> str:
    """Write the content stored in a scratchpad key to a file at path.

    Reads the auto-saved scratchpad key (e.g. _tc_r5_fetch_page_text shown in a truncation
    notice) and writes it to the given path. The path follows the same resolution rules as
    write_file. Creates parent directories automatically.

    Use this instead of write_file when the content to write is already in the scratchpad
    (e.g. a large page fetch that was auto-saved), to avoid putting large content into tool
    call arguments where JSON encoding can cause errors.
    """
    import sys as _sys
    _code_dir = str(Path(__file__).resolve().parents[2])
    if _code_dir not in _sys.path:
        _sys.path.insert(0, _code_dir)
    from scratchpad import scratch_load as _scratch_load

    content = _scratch_load(scratch_key)
    if "not found" in content.lower() and len(content) < 200:
        return f"Error: scratchpad key {scratch_key!r} does not exist"
    try:
        target_path = _resolve_safe_path(path)
    except ValueError as err:
        return f"Error: {err}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return f"Wrote {target_path.relative_to(WORKSPACE_ROOT).as_posix()} ({len(content):,} chars from scratch key {scratch_key!r})"
