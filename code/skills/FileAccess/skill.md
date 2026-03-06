# FileAccess Skill

## Purpose
Provide safe workspace-constrained file access for write, append, read, and listing operations.

## Interface
- Module: `code/skills/FileAccess/file_access_skill.py`
- Primary functions:
  - `write_text_file(file_path: str, text: str)`
  - `append_text_file(file_path: str, text: str)`
  - `read_text_file(file_path: str, max_chars: int = 8000)`
  - `list_data_files()`
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
- Typical trigger phrases:
  - `create file <name>`
  - `write ... to file <path>`
  - `append ... to file <path>`
  - `read file <path>`
  - `write the system information to <path>.csv`
  - `write ... in CSV format`

## Output
- Returns status messages for write/append/list operations.
- Writing a SystemInfo string to a `.csv` file converts it to `key,value` CSV rows automatically.
- Returns file content for read operations.
- Returns parse guidance when instruction intent/path cannot be resolved.

## Examples
- `execute_file_instruction("write hello world to file x.txt")`
- `execute_file_instruction("append done to file ./data/content.txt")`
- `execute_file_instruction("read file ./data/content.txt")`
- `execute_file_instruction("create file abc.csv and write header1,header2 into it")`
- `execute_file_instruction("write the system information to ./data/<name>.csv")`
