# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# FileAccess skill module for the MiniAgentFramework.
#
# Provides safe file read/write/append operations constrained to the workspace root, with sensible
# defaults for relative paths and a natural-language command entrypoint for prompt-triggered use.
#
# Path behavior:
#   - bare file name like "x.txt" resolves to ./data/x.txt
#   - path starting with "./" resolves from workspace root
#   - absolute paths are allowed only when they remain inside workspace root
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import csv
import io
import re
from pathlib import Path

from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
WORKSPACE_ROOT   = get_workspace_root()
DEFAULT_DATA_DIR = WORKSPACE_ROOT / "data"
_PROMPT_PATH_RE  = re.compile(
    r"(?<![\w./-])((?:\./)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:csv|txt|md|json|jsonl|log))(?![\w./-])",
    re.IGNORECASE,
)
EXCLUDED_DIRS = frozenset({
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
})


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
        elif "/" in normalized:
            candidate = (WORKSPACE_ROOT / normalized).resolve()
        else:
            candidate = (DEFAULT_DATA_DIR / normalized).resolve()

    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as path_error:
        raise ValueError(f"Path escapes workspace root and is not allowed: {file_path}") from path_error

    return candidate


# ----------------------------------------------------------------------------------------------------
def _extract_path_from_prompt(prompt: str) -> str:
    explicit_match = re.search(r"\bfile\s+([\"'][^\"']+[\"']|[^\s]+)", prompt, re.IGNORECASE)
    if explicit_match:
        return explicit_match.group(1).strip().strip('"').strip("'")

    path_match = _PROMPT_PATH_RE.search(prompt or "")
    if not path_match:
        return ""
    return path_match.group(1).strip().strip('"').strip("'")


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
# PLANNER_TOOLS: explicit tool definitions for find_files and find_folders so the orchestrator
# exposes them with typed parameter schemas rather than deriving them from bare signatures.
PLANNER_TOOLS = [
    {
        "name":        "find_files",
        "function":    "find_files",
        "description": "Search the workspace for files whose name contains a keyword fragment. Returns a list of matching relative paths. Use this when you know part of a filename but not the exact path.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type":        "string",
                    "description": "Case-insensitive fragment to match against file names.",
                },
                "search_root": {
                    "type":        "string",
                    "description": "Optional workspace-relative directory to restrict the search (e.g. 'data' or 'controldata'). Leave empty to search the whole workspace.",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name":        "find_folders",
        "function":    "find_folders",
        "description": "Search the workspace for folders whose name contains a keyword fragment. Returns a list of matching relative paths. Use this when you need to locate a directory by partial name.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type":        "string",
                    "description": "Case-insensitive fragment to match against folder names.",
                },
                "search_root": {
                    "type":        "string",
                    "description": "Optional workspace-relative directory to restrict the search. Leave empty to search the whole workspace.",
                },
            },
            "required": ["keyword"],
        },
    },
]

PRIMARY_PLANNER_TOOL = "find_files"


# ----------------------------------------------------------------------------------------------------
def write_text_file(file_path: str, text: str) -> str:
    try:
        target_path = _resolve_safe_path(file_path)
    except ValueError as err:
        return f"Error: {err}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(_coerce_text_for_target(target_path=target_path, text=text), encoding="utf-8")
    return f"Wrote {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def append_text_file(file_path: str, text: str) -> str:
    try:
        target_path = _resolve_safe_path(file_path)
    except ValueError as err:
        return f"Error: {err}"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    text_to_write = str(text).replace("\\n", "\n")  # unescape literal \n from model output
    if not text_to_write.endswith("\n"):
        text_to_write += "\n"
    with target_path.open("a", encoding="utf-8") as output_file:
        output_file.write(text_to_write)
    return f"Appended {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def read_text_file(file_path: str, max_chars: int = 8000) -> str:
    try:
        target_path = _resolve_safe_path(file_path)
    except ValueError as err:
        return f"Error: {err}"
    if not target_path.exists():
        return f"File not found: {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"

    content = target_path.read_text(encoding="utf-8")
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n[truncated]"


# ----------------------------------------------------------------------------------------------------
def list_data_files() -> str:
    _ensure_data_dir()
    file_paths = [item.relative_to(WORKSPACE_ROOT).as_posix() for item in sorted(DEFAULT_DATA_DIR.rglob("*")) if item.is_file()]
    if not file_paths:
        return "No files found under data/."
    return "\n".join(file_paths)


# ----------------------------------------------------------------------------------------------------
def find_files(keyword: str, search_root: str = "") -> str:
    """Return all files under the workspace whose name contains *keyword* (case-insensitive).

    *search_root* is a workspace-relative directory to restrict the search (e.g. "data" or
    "controldata").  Defaults to the full workspace root when empty or omitted.
    """
    keyword_clean = str(keyword or "").strip().lower()
    if not keyword_clean:
        return "Error: keyword must not be empty."

    if search_root:
        try:
            base = _resolve_safe_path(search_root if "/" in search_root else search_root + "/placeholder")
            base = base.parent if base.suffix else base
        except ValueError:
            return f"Error: search_root '{search_root}' escapes workspace."
    else:
        base = WORKSPACE_ROOT

    matches = [
        p.relative_to(WORKSPACE_ROOT).as_posix()
        for p in sorted(base.rglob("*"))
        if p.is_file()
        and keyword_clean in p.name.lower()
        and not any(part in EXCLUDED_DIRS for part in p.relative_to(base).parts)
    ]

    if not matches:
        return f"No files found containing '{keyword}'" + (f" under {search_root}" if search_root else "") + "."
    return "\n".join(matches)


# ----------------------------------------------------------------------------------------------------
def find_folders(keyword: str, search_root: str = "") -> str:
    """Return all directories under the workspace whose name contains *keyword* (case-insensitive).

    *search_root* is a workspace-relative directory to restrict the search.
    Defaults to the full workspace root when empty or omitted.
    """
    keyword_clean = str(keyword or "").strip().lower()
    if not keyword_clean:
        return "Error: keyword must not be empty."

    if search_root:
        try:
            base = _resolve_safe_path(search_root if "/" in search_root else search_root + "/placeholder")
            base = base.parent if base.suffix else base
        except ValueError:
            return f"Error: search_root '{search_root}' escapes workspace."
    else:
        base = WORKSPACE_ROOT

    matches = [
        p.relative_to(WORKSPACE_ROOT).as_posix()
        for p in sorted(base.rglob("*"))
        if p.is_dir()
        and keyword_clean in p.name.lower()
        and not any(part in EXCLUDED_DIRS for part in p.relative_to(base).parts)
    ]

    if not matches:
        return f"No folders found containing '{keyword}'" + (f" under {search_root}" if search_root else "") + "."
    return "\n".join(matches)


# ----------------------------------------------------------------------------------------------------
def execute_file_instruction(user_prompt: str) -> str:
    prompt = str(user_prompt or "").strip()
    lowered = prompt.lower()

    raw_path = _extract_path_from_prompt(prompt)
    if not raw_path:
        return "No file path found in instruction. Include 'file <path>'."

    if "append" in lowered:
        append_match = re.search(r"append\s+(.+?)\s+to\s+file\b", prompt, re.IGNORECASE)
        if not append_match:
            append_match = re.search(rf"append\s+(.+?)\s+to\s+(?:an?\s+)?{re.escape(raw_path)}\b", prompt, re.IGNORECASE)
        if not append_match:
            return "Unable to parse append content. Use: append <text> to file <path>."

        content = append_match.group(1).strip()
        return append_text_file(file_path=raw_path, text=f"{content}\n")

    if "write" in lowered:
        if any(
            phrase in lowered for phrase in (
                "system information",
                "system info",
                "system stats",
                "system health",
                "runtime info",
                "environment information",
            )
        ):
            from skills.SystemInfo.system_info_skill import get_system_info_string

            return write_text_file(file_path=raw_path, text=get_system_info_string())

        write_match = re.search(r"write\s+(.+?)\s+to\s+file\b", prompt, re.IGNORECASE)
        if not write_match:
            write_match = re.search(rf"write\s+(.+?)\s+to\s+(?:an?\s+)?{re.escape(raw_path)}\b", prompt, re.IGNORECASE)
        if not write_match:
            # Support phrasing like: "create file x and write <text> into it".
            write_match = re.search(r"write\s+(.+?)\s+into\s+it\b", prompt, re.IGNORECASE)

        if not write_match:
            return "Unable to parse write content. Use: write <text> to file <path>."

        content = write_match.group(1).strip()
        return write_text_file(file_path=raw_path, text=content + "\n")

    if "read" in lowered:
        return read_text_file(file_path=raw_path)

    if "list" in lowered and "data" in lowered:
        return list_data_files()

    return "Instruction not recognized. Supported intents: write, append, read, list data files."
