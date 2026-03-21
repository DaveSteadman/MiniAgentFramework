# FileAccess Skill

## Purpose
Interface for all file read, write, append, and search operations. All paths are workspace-relative; bare file names resolve to `./data/`. Paths that escape the workspace root are rejected.

## Trigger keyword: file

## Interface
- Module: `code/skills/FileAccess/file_access_skill.py`
- Functions:
  - `write_file(path: str, content: str)`
  - `append_file(path: str, content: str)`
  - `read_file(path: str, max_chars: int = 8000)`
  - `find_files(keywords: list[str], search_root: str = "")`
  - `find_folders(keywords: list[str], search_root: str = "")`

## Parameters

### `write_file(path, content)`
- `path` *(required)* - workspace-relative path. A bare name like `"x.txt"` resolves to `data/x.txt`. A path starting with `"./"` resolves from workspace root.
- `content` *(required)* - content to write. Overwrites the file if it exists.

### `append_file(path, content)`
- `path` *(required)* - same path rules as `write_file`.
- `content` *(required)* - content to append. A newline is added automatically if missing.

### `read_file(path, max_chars = 8000)`
- `path` *(required)* - same path rules as `write_file`.
- `max_chars` *(optional, default 8000)* - maximum characters to return; content is truncated with `[truncated]` if exceeded.

### `find_files(keywords, search_root = "")`
- `keywords` *(required)* - list of case-insensitive fragments that must ALL appear in the file name, e.g. `["pulse", "2026"]`.
- `search_root` *(optional, default "")* - workspace-relative directory to restrict the search, e.g. `"data"`. Leave empty to search the whole workspace.

### `find_folders(keywords, search_root = "")`
- `keywords` *(required)* - list of case-insensitive fragments that must ALL appear in the folder name.
- `search_root` *(optional, default "")* - workspace-relative directory to restrict the search. Leave empty to search the whole workspace.

## Output
- `write_file(...)` - returns `"Wrote data/filename.txt"` on success, or `"Error: ..."` on failure.
- `append_file(...)` - returns `"Appended data/filename.txt"` on success, or `"Error: ..."` on failure.
- `read_file(...)` - returns the file content as a string, or `"File not found: ..."` if the file does not exist.
- `find_files(...)` - returns a newline-separated list of matching workspace-relative paths, or a `"No files found..."` message.
- `find_folders(...)` - returns a newline-separated list of matching workspace-relative paths, or a `"No folders found..."` message.

## Triggers
Invoke this skill when the prompt contains any of these concepts or phrases:
- `write to file`, `create file`, `save to file`
- `append to file`, `add to file`
- `read file`, `show file`, `open file`, `contents of`
- `find file`, `find folder`, `locate file`, `search for file`

## Examples
- `write_file("notes/meeting.txt", "Discuss project timeline")` - creates or overwrites the file
  - Returns: `"Wrote data/notes/meeting.txt"`
- `append_file("data/log.txt", "new entry")` - appends a line
  - Returns: `"Appended data/log.txt"`
- `read_file(path="data/log.txt")` - returns full content up to 8000 chars
- `find_files(["pulse"], "data")` - find files with "pulse" in the name under data/
  - Returns: `"data/pulse_log.csv\ndata/sys_pulse.csv"`
- `find_files(["test", "2026"])` - find files whose name contains both fragments
- `find_folders(["2026-03"])` - find folders containing "2026-03" in the name
