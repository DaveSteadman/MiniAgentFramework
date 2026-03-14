# TaskManagement Skill

## Purpose
Create, query, update, enable, disable, and delete scheduled tasks stored as JSON files in
`controldata/schedules/`. Each task defines a schedule (interval in minutes, or daily at a
wall-clock time) and one or more prompt strings that the scheduler runs automatically.

## Interface
- Module: `code/skills/TaskManagement/task_management_skill.py`
- Primary functions:
  - `list_tasks()`
  - `get_task(name: str)`
  - `create_task(name: str, schedule: str, prompt: str)`
  - `set_task_enabled(name: str, enabled: bool)`
  - `set_task_schedule(name: str, schedule: str)`
  - `set_task_prompt(name: str, prompt: str)`
  - `delete_task(name: str)`

## Input

### `list_tasks()`
No arguments. Returns a summary of all tasks.

### `get_task(name)`
- `name`: exact task name (case-insensitive).

### `create_task(name, schedule, prompt)`
- `name`: unique task name; alphanumeric, hyphens, underscores only.
- `schedule`: interval as a plain integer string (e.g. `"60"` = every 60 minutes) OR a daily
  wall-clock time as `"HH:MM"` (e.g. `"08:30"` = every day at 08:30).
- `prompt`: the natural-language instruction the scheduler will run on each firing.

### `set_task_enabled(name, enabled)`
- `name`: task name.
- `enabled`: `true` to enable, `false` to disable.

### `set_task_schedule(name, schedule)`
- `name`: task name.
- `schedule`: same format as `create_task` - integer minutes or `"HH:MM"`.

### `set_task_prompt(name, prompt)`
- `name`: task name.
- `prompt`: replacement prompt text.

### `delete_task(name)`
- `name`: task name to permanently remove.

## Output
All functions return a plain-text status string confirming the operation or describing any error.
`list_tasks()` returns one line per task: `[on/off]  name  schedule  prompt-preview`.
`get_task()` returns a formatted block with all fields of the task.

## Examples
- `list_tasks()`
- `get_task("PerformanceHeadroom")`
- `create_task("DailyWeather", "08:00", "Check the weather forecast for today and summarise it.")`
- `create_task("HourlyMemCheck", "60", "Check free RAM and log it to data/memlog.csv.")`
- `set_task_enabled("PerformanceHeadroom", False)`
- `set_task_enabled("DailyWeather", True)`
- `set_task_schedule("HourlyMemCheck", "30")`
- `set_task_schedule("DailyWeather", "07:30")`
- `set_task_prompt("DailyWeather", "Get today's weather forecast and temperature for London.")`
- `delete_task("OldTask")`
