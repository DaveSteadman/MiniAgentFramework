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
import re
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
            candidate = (DEFAULT_DATA_DIR / normalized).resolve()

    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as path_error:
        raise ValueError(f"Path escapes workspace root and is not allowed: {file_path}") from path_error

    return candidate


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def write_text_file(file_path: str, text: str) -> str:
    target_path = _resolve_safe_path(file_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(str(text), encoding="utf-8")
    return f"Wrote {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def append_text_file(file_path: str, text: str) -> str:
    target_path = _resolve_safe_path(file_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("a", encoding="utf-8") as output_file:
        output_file.write(str(text))
    return f"Appended {target_path.relative_to(WORKSPACE_ROOT).as_posix()}"


# ----------------------------------------------------------------------------------------------------
def read_text_file(file_path: str, max_chars: int = 8000) -> str:
    target_path = _resolve_safe_path(file_path)
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
def execute_file_instruction(user_prompt: str) -> str:
    prompt = str(user_prompt or "").strip()
    lowered = prompt.lower()

    file_match = re.search(r"\bfile\s+([\"'][^\"']+[\"']|[^\s]+)", prompt, re.IGNORECASE)
    if not file_match:
        return "No file path found in instruction. Include 'file <path>'."

    raw_path = file_match.group(1).strip().strip('"').strip("'")

    if "append" in lowered:
        append_match = re.search(r"append\s+(.+?)\s+to\s+file\b", prompt, re.IGNORECASE)
        if not append_match:
            return "Unable to parse append content. Use: append <text> to file <path>."

        content = append_match.group(1).strip()
        return append_text_file(file_path=raw_path, text=f"{content}\n")

    if "write" in lowered:
        write_match = re.search(r"write\s+(.+?)\s+to\s+file\b", prompt, re.IGNORECASE)
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
