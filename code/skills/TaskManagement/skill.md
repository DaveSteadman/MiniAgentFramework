# TaskManagement Skill

## Purpose
Create, query, update, enable, disable, and delete scheduled tasks stored as JSON files in `controldata/schedules/`. Each task defines a schedule and a prompt string that the scheduler runs automatically on each firing.

## Trigger keyword: task

## Interface
- Module: `code/skills/TaskManagement/task_management_skill.py`
- Functions:
  - `list_tasks()`
  - `get_task(name: str)`
  - `create_task(name: str, schedule: str, prompt: str)`
  - `set_task_enabled(name: str, enabled: bool)`
  - `set_task_schedule(name: str, schedule: str)`
  - `set_task_prompt(name: str, prompt: str)`
  - `delete_task(name: str)`

## Parameters

### `list_tasks()`
No parameters.

### `get_task(name)`
- `name` *(required)* - exact task name (case-insensitive).

### `create_task(name, schedule, prompt)`
- `name` *(required)* - unique task name; alphanumeric, hyphens, underscores only.
- `schedule` *(required)* - interval as a plain integer string, e.g. `"60"` = every 60 minutes; OR a daily wall-clock time as `"HH:MM"`, e.g. `"08:30"` = every day at 08:30.
- `prompt` *(required)* - the natural-language instruction the scheduler will run on each firing.

### `set_task_enabled(name, enabled)`
- `name` *(required)* - task name.
- `enabled` *(required)* - `true` to enable, `false` to disable.

### `set_task_schedule(name, schedule)`
- `name` *(required)* - task name.
- `schedule` *(required)* - same format as `create_task`: integer minutes or `"HH:MM"`.

### `set_task_prompt(name, prompt)`
- `name` *(required)* - task name.
- `prompt` *(required)* - replacement prompt text.

### `delete_task(name)`
- `name` *(required)* - name of the task to permanently remove.

## Output
All functions return a plain-text status string confirming the operation or describing any error.
- `list_tasks()` - returns one line per task: `[on/off]  name  schedule  prompt-preview`.
- `get_task(...)` - returns a formatted block with all fields of the named task.
- All other functions return a confirmation or error string.

## Triggers
Invoke this skill when the prompt contains any of these concepts or phrases:
- `create task`, `add task`, `schedule a task`
- `list tasks`, `show tasks`, `what tasks are scheduled`
- `enable task`, `disable task`, `turn on task`, `turn off task`
- `update task`, `change schedule`, `delete task`, `remove task`

## Scratchpad integration
Not applicable for scheduled tasks.  Each task fires in a fresh subprocess where the
scratchpad `_STORE` is always empty - values saved by a prior skill call within the
scheduled prompt will not survive to a subsequent one.  Scratchpad can be used normally
when TaskManagement is invoked as one step within an interactive session plan.

## Examples
- `list_tasks()` - show all scheduled tasks
- `get_task("PerformanceHeadroom")` - show full details of the named task
- `create_task("DailyWeather", "08:00", "Check the weather forecast for today.")` - create a daily task
  - Returns: `"Task 'DailyWeather' created."`
- `create_task("HourlyMemCheck", "60", "Check free RAM and log it to data/memlog.csv.")` - create an interval task
- `set_task_enabled("PerformanceHeadroom", False)` - disable the task
  - Returns: `"Task 'PerformanceHeadroom' updated."`
- `set_task_schedule("HourlyMemCheck", "30")` - change to every 30 minutes
- `delete_task("OldTask")` - permanently remove the task
