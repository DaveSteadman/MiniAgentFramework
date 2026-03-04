# DateTime Skill

## Purpose
Return current date and current time as separate values.

## Interface
- Module: `code/skills/DateTime/datetime_skill.py`
- Function: `get_datetime_data()`

## Input
- `get_datetime_data()`
  - No arguments.

## Output
- `get_datetime_data()` returns a structured object:
  - `{ "date": "YYYY-MM-DD", "time": "HH:MM:SS" }`

## Example
- `get_datetime_data()` -> `{ "date": "2026-03-03", "time": "21:15:42" }`
