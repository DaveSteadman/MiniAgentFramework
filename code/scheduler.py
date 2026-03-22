# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Lightweight schedule management utilities for MiniAgentFramework scheduler mode.
#
# Provides:
#   llm_lock           -- module-level threading.Lock that any LLM-calling code acquires while active.
#                         Enforces single-LLM exclusivity: only one task runs at a time.
#   load_schedules_dir -- scans a directory for *.json schedule files and merges all tasks lists.
#   is_task_due        -- pure function; tests whether a task should fire given current time.
#
# Schedule directory layout:
#   controldata/schedules/*.json   each file must have a top-level "tasks" list.
#   Files are loaded in sorted filename order; tasks from all files are merged into one flat list.
#
# Schedule types:
#   interval   fires every N minutes  {"type": "interval", "minutes": N}
#   daily      fires once per day at a fixed wall-clock time  {"type": "daily", "time": "HH:MM"}
#
# The run_scheduler_mode function lives in main.py alongside run_chat_mode so that
# orchestrate_prompt is accessible without a circular import.
#
# Related modules:
#   - main.py    -- imports this module and contains run_scheduler_mode
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import sys
import threading
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: LLM LOCK
# ====================================================================================================
# Acquire this lock before any LLM call; release when done.
# The scheduler loop checks .locked() before starting a new task and skips if busy.
llm_lock: threading.Lock = threading.Lock()


# ====================================================================================================
# MARK: SCHEDULE LOADING
# ====================================================================================================
def load_schedules_dir(schedules_dir: Path) -> list[dict]:
    """Scan schedules_dir for *.json files and return a merged flat list of all task dicts.

    Files are processed in sorted filename order.  Each file must contain a top-level
    'tasks' list.  Files with invalid JSON or missing the key are skipped with a warning
    printed to stderr so one bad file does not prevent the others from loading.
    """
    if not schedules_dir.exists():
        raise FileNotFoundError(f"Schedules directory not found: {schedules_dir}")

    tasks: list[dict] = []
    json_files = sorted(schedules_dir.glob("*.json"))

    if not json_files:
        print(f"[scheduler] Warning: no *.json files found in {schedules_dir}", file=sys.stderr)
        return tasks

    for json_path in json_files:
        raw = json_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[scheduler] Skipping {json_path.name}: invalid JSON ({exc})", file=sys.stderr)
            continue

        file_tasks = data.get("tasks")
        if not isinstance(file_tasks, list):
            print(f"[scheduler] Skipping {json_path.name}: missing top-level 'tasks' list.", file=sys.stderr)
            continue

        tasks.extend(file_tasks)

    return tasks


# ====================================================================================================
# MARK: SCHEDULE EVALUATION
# ====================================================================================================
def initial_last_run(task: dict, reference: datetime) -> "datetime | None":
    """Return the value to store in last_run when a task is first registered (startup or hot-add).

    interval  -- return reference so the first fire occurs after a full interval, not immediately.
    daily     -- return reference if the scheduled wall-clock time has already passed today
                 (preventing an immediate spurious fire on startup); return None if it hasn't
                 been reached yet so the task still fires at its proper time later today.
    """
    schedule = task.get("schedule", {})
    stype    = schedule.get("type", "")

    if stype == "interval":
        return reference

    if stype == "daily":
        target_str = schedule.get("time", "00:00")
        try:
            target_time = datetime.strptime(target_str, "%H:%M").time()
        except ValueError:
            return reference  # malformed - treat as already fired today
        if reference.time() >= target_time:
            return reference  # time has passed today - defer to tomorrow
        return None  # time not yet reached - will fire naturally later today

    return None


def is_task_due(task: dict, last_run: datetime | None, now: datetime) -> bool:
    """Return True if the task should fire given the current time and its last-run timestamp.

    interval  -- fires immediately on first invocation (last_run is None), then every N minutes.
    daily     -- fires once per calendar day at the configured wall-clock time.
    """
    schedule      = task.get("schedule", {})
    schedule_type = schedule.get("type", "")

    if schedule_type == "interval":
        if last_run is None:
            return True
        elapsed_minutes = (now - last_run).total_seconds() / 60.0
        return elapsed_minutes >= schedule.get("minutes", 60)

    if schedule_type == "daily":
        target_str = schedule.get("time", "00:00")
        try:
            target_time = datetime.strptime(target_str, "%H:%M").time()
        except ValueError:
            return False  # malformed time string - never fire
        if now.time() < target_time:
            return False
        if last_run is None:
            return True  # time reached and never run - fire now
        return last_run.date() < now.date()

    return False
