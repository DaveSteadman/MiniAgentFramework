# FileAccess Skill

## Purpose
Provide safe workspace-constrained file access for write, append, read, listing, and name-based search operations.

## Interface
- Module: `code/skills/FileAccess/file_access_skill.py`
- Primary functions:
  - `write_text_file(file_path: str, text: str)`
  - `append_text_file(file_path: str, text: str)`
  - `read_text_file(file_path: str, max_chars: int = 8000)`
  - `list_data_files()`
  - `find_files(keyword: str, search_root: str = "")`
  - `find_folders(keyword: str, search_root: str = "")`
  - `execute_file_instruction(user_prompt: str)`

## Path Rules
- Bare path like `x.txt` resolves to `./data/x.txt`.
- Relative paths with a directory component like `data/x.csv` or `logs/run.txt` resolve from workspace root.
- Path starting with `./` resolves from workspace root.
- Absolute paths are permitted only if they resolve inside workspace root.
- Paths escaping workspace root are rejected.

## Input
- `file_path`: target file path.
- `text`: content to write or append.
- `user_prompt`: natural-language instruction for command parsing.
- `keyword`: case-insensitive name fragment for find operations.
- `search_root`: optional workspace-relative directory to restrict find searches.
- Typical trigger phrases:
  - `create file <name>`
  - `write ... to file <path>`
  - `append ... to file <path>`
  - `read file <path>`
  - `find file named <keyword>`
  - `find folder named <keyword>`
  - `find files containing <keyword> in <folder>`

## Output
- Returns status messages for write/append/list operations.
- Writing a SystemInfo string to a `.csv` file converts it to `key,value` CSV rows automatically.
- Returns file content for read operations.
- `find_files` returns a newline-separated list of workspace-relative file paths whose names contain the keyword, or a "not found" message.
- `find_folders` returns a newline-separated list of workspace-relative folder paths whose names contain the keyword, or a "not found" message.
- Returns parse guidance when instruction intent/path cannot be resolved.

## Examples
- `execute_file_instruction("write hello world to file x.txt")`
- `execute_file_instruction("append done to file ./data/content.txt")`
- `execute_file_instruction("read file ./data/content.txt")`
- `find_files("analysis")` - returns all files with "analysis" in the name
- `find_files("pulse", "data")` - returns all files with "pulse" in the name under data/
- `find_folders("2026-03")` - returns all folders containing "2026-03" in the name
