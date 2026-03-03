# DateTime Skill

## Purpose
Provide a current date-time string that can be prepended to a later LLM prompt.

## Interface
- Module: `code/skills/DateTime/datetime_skill.py`
- Primary function: `get_datetime_string()`
- Optional function: `build_prompt_with_datetime(prompt: str)`

## Input
- `get_datetime_string()`
  - No arguments.
- `build_prompt_with_datetime(prompt: str)`
  - `prompt`: the downstream LLM prompt text.

## Output
- `get_datetime_string()` returns a string in local time:
  - Format: `Current date/time: YYYY-MM-DD HH:MM:SS`
- `build_prompt_with_datetime(prompt: str)` returns:
  - `Current date/time: YYYY-MM-DD HH:MM:SS\n<prompt>`

## Example
- `get_datetime_string()` -> `Current date/time: 2026-03-03 21:15:42`
- `build_prompt_with_datetime("Summarize these notes")` ->
  - `Current date/time: 2026-03-03 21:15:42`
  - `Summarize these notes`
