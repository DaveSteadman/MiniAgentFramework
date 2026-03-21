# Skills Summary

Single JSON payload for orchestration planning.

{
  "schema_version": "1.0",
  "skills_root": "code/skills",
  "skills": [
    {
      "skill_name": "CodeExecute Skill",
      "relative_path": "code/skills/CodeExecute/skill.md",
      "purpose": "- Execute a self-contained Python code snippet and return the captured stdout.",
      "module": "code/skills/CodeExecute/code_execute_skill.py",
      "trigger_keyword": "calculate",
      "functions": [
        "run_python_snippet(...)",
        "run_python_snippet(code)",
        "run_python_snippet(code: str)",
        "run_python_snippet(code=\"import math\\nfor i in range(1, 6):\\n    print(i, math.factorial(i))\")",
        "run_python_snippet(code=\"print('index,square')\\nfor i in range(1, 6):\\n    print(i, i*i)\")"
      ],
      "inputs": [],
      "outputs": [
        "`run_python_snippet(...)` - returns captured stdout as a plain string. Returns `\"Error: ...\"` if the snippet raises an exception, times out, or produces no output."
      ]
    },
    {
      "skill_name": "DateTime Skill",
      "relative_path": "code/skills/DateTime/skill.md",
      "purpose": "Return the current date and current time as separate values. Use this when a prompt asks what the date, time, day, or year is.",
      "module": "code/skills/DateTime/datetime_skill.py",
      "trigger_keyword": "datetime",
      "functions": [
        "get_datetime_data()",
        "get_day_name()",
        "get_month_name()"
      ],
      "inputs": [],
      "outputs": [
        "`get_datetime_data()` - returns a dict with two string fields:",
        "`date` (str) - current date as `\"YYYY-MM-DD\"`",
        "`time` (str) - current time as `\"HH:MM:SS\"`",
        "`get_day_name()` - returns the full name of the current day of the week, e.g. `\"Saturday\"`",
        "`get_month_name()` - returns the full name of the current month, e.g. `\"March\"`"
      ]
    },
    {
      "skill_name": "FileAccess Skill",
      "relative_path": "code/skills/FileAccess/skill.md",
      "purpose": "Interface for all file read, write, append, and search operations. All paths are workspace-relative; bare file names resolve to `./data/`. Paths that escape the workspace root are rejected.",
      "module": "code/skills/FileAccess/file_access_skill.py",
      "trigger_keyword": "file",
      "functions": [
        "append_file(\"data/log.txt\", \"new entry\")",
        "append_file(...)",
        "append_file(path, content)",
        "append_file(path: str, content: str)",
        "find_files(...)",
        "find_files([\"pulse\"], \"data\")",
        "find_files([\"test\", \"2026\"])",
        "find_files(keywords, search_root = \"\")",
        "find_files(keywords: list[str], search_root: str = \"\")",
        "find_folders(...)",
        "find_folders([\"2026-03\"])",
        "find_folders(keywords, search_root = \"\")",
        "find_folders(keywords: list[str], search_root: str = \"\")",
        "read_file(...)",
        "read_file(path, max_chars = 8000)",
        "read_file(path: str, max_chars: int = 8000)",
        "read_file(path=\"data/log.txt\")",
        "write_file(\"notes/meeting.txt\", \"Discuss project timeline\")",
        "write_file(...)",
        "write_file(path, content)",
        "write_file(path: str, content: str)"
      ],
      "inputs": [],
      "outputs": [
        "`write_file(...)` - returns `\"Wrote data/filename.txt\"` on success, or `\"Error: ...\"` on failure.",
        "`append_file(...)` - returns `\"Appended data/filename.txt\"` on success, or `\"Error: ...\"` on failure.",
        "`read_file(...)` - returns the file content as a string, or `\"File not found: ...\"` if the file does not exist.",
        "`find_files(...)` - returns a newline-separated list of matching workspace-relative paths, or a `\"No files found...\"` message.",
        "`find_folders(...)` - returns a newline-separated list of matching workspace-relative paths, or a `\"No folders found...\"` message."
      ]
    },
    {
      "skill_name": "Memory Skill",
      "relative_path": "code/skills/Memory/skill.md",
      "purpose": "Persist and recall durable user-stated facts across sessions - identity, preferences, project context, and environment facts. A newer fact on the same subject supersedes the older one. Do not store questions, commands, or ephemeral data such as current time or system stats. Facts persist in `memory_store.json` with category, timestamps, and access tracking.",
      "module": "code/skills/Memory/memory_skill.py",
      "trigger_keyword": "memory",
      "functions": [
        "extract_environment_facts(...)",
        "extract_environment_facts(user_prompt)",
        "extract_environment_facts(user_prompt: str)",
        "get_memory_store_text()",
        "recall_relevant_memories(\"what is our workspace path\")",
        "recall_relevant_memories(...)",
        "recall_relevant_memories(user_prompt, limit = 5, min_score = 0.25)",
        "recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)",
        "store_prompt_memories(\"Our workspace path is c:/Util/GithubRepos/MiniAgentFramework\")",
        "store_prompt_memories(\"Our workspace path is c:/Util/NewLocation\")",
        "store_prompt_memories(...)",
        "store_prompt_memories(user_prompt)",
        "store_prompt_memories(user_prompt: str)"
      ],
      "inputs": [],
      "outputs": [
        "`store_prompt_memories(...)` - returns `\"Stored N new memory fact(s).\"` or `\"Updated N existing memory fact(s).\"`.",
        "`recall_relevant_memories(...)` - returns a formatted ranked list of memories with category and relevance score.",
        "`extract_environment_facts(...)` - returns a list of candidate environment facts extracted from the prompt.",
        "`get_memory_store_text()` - returns the full pretty-printed JSON of the memory store."
      ]
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information including OS name, Python and Ollama versions, RAM usage, and disk usage. Use this for any prompt about the machine, hardware, runtime environment, available resources, or version details. Do not use this for web or file queries.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "trigger_keyword": "systeminfo",
      "functions": [
        "get_system_info_dict()"
      ],
      "inputs": [],
      "outputs": [
        "`get_system_info_dict()` - returns a dict with individually addressable fields:",
        "`os` (str) - OS name, e.g. `\"Windows\"`",
        "`python_version` (str) - e.g. `\"3.10.11\"`",
        "`ollama_version` (str) - e.g. `\"0.18.0\"`",
        "`ram_used_gb` (float) - RAM in use in GiB",
        "`ram_available_gb` (float) - RAM free in GiB",
        "`disk_used_gb` (float) - disk used in GiB",
        "`disk_available_gb` (float) - disk free in GiB"
      ]
    },
    {
      "skill_name": "TaskManagement Skill",
      "relative_path": "code/skills/TaskManagement/skill.md",
      "purpose": "Create, query, update, enable, disable, and delete scheduled tasks stored as JSON files in `controldata/schedules/`. Each task defines a schedule and a prompt string that the scheduler runs automatically on each firing.",
      "module": "code/skills/TaskManagement/task_management_skill.py",
      "trigger_keyword": "task",
      "functions": [
        "create_task(\"DailyWeather\", \"08:00\", \"Check the weather forecast for today.\")",
        "create_task(\"HourlyMemCheck\", \"60\", \"Check free RAM and log it to data/memlog.csv.\")",
        "create_task(name, schedule, prompt)",
        "create_task(name: str, schedule: str, prompt: str)",
        "delete_task(\"OldTask\")",
        "delete_task(name)",
        "delete_task(name: str)",
        "get_task(\"PerformanceHeadroom\")",
        "get_task(...)",
        "get_task(name)",
        "get_task(name: str)",
        "list_tasks()",
        "set_task_enabled(\"PerformanceHeadroom\", False)",
        "set_task_enabled(name, enabled)",
        "set_task_enabled(name: str, enabled: bool)",
        "set_task_prompt(name, prompt)",
        "set_task_prompt(name: str, prompt: str)",
        "set_task_schedule(\"HourlyMemCheck\", \"30\")",
        "set_task_schedule(name, schedule)",
        "set_task_schedule(name: str, schedule: str)"
      ],
      "inputs": [],
      "outputs": [
        "`list_tasks()` - returns one line per task: `[on/off]  name  schedule  prompt-preview`.",
        "`get_task(...)` - returns a formatted block with all fields of the named task.",
        "All other functions return a confirmation or error string."
      ]
    },
    {
      "skill_name": "WebSearch Skill",
      "relative_path": "code/skills/WebSearch/skill.md",
      "purpose": "Search the web using DuckDuckGo and return ranked results with title, URL, and snippet. No API key required. Use `search_web_text` when results will be read directly by the LLM; use `search_web` when the caller needs structured data. This skill only returns results - it does not persist or save anything.",
      "module": "code/skills/WebSearch/web_search_skill.py",
      "trigger_keyword": "search",
      "functions": [
        "search_web(\"Eiffel Tower height\")",
        "search_web(...)",
        "search_web(query, max_results = 5, timeout_seconds = 15)",
        "search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)",
        "search_web_text(\"Python 3.14 release notes\", max_results=3)",
        "search_web_text(...)",
        "search_web_text(query, max_results = 5, timeout_seconds = 15)",
        "search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)"
      ],
      "inputs": [],
      "outputs": [
        "`search_web(...)` - returns `list[dict]`, each entry with `rank` (int), `title` (str), `url` (str), `snippet` (str). On error: single-entry list with `rank=0` and `snippet` describing the failure.",
        "`search_web_text(...)` - returns a plain-text formatted block with rank, title, URL, and snippet per result. Ready for direct LLM consumption."
      ]
    },
    {
      "skill_name": "Wikipedia Skill",
      "relative_path": "code/skills/Wikipedia/skill.md",
      "purpose": "Look up a topic on Wikipedia and return a plain-text article summary. Use this for authoritative factual reference data about a person, place, concept, event, or technology. For current news or live data, use WebSearch instead.",
      "module": "code/skills/Wikipedia/wikipedia_skill.py",
      "trigger_keyword": "wikipedia",
      "functions": [
        "lookup_wikipedia(\"Eiffel Tower\")",
        "lookup_wikipedia(\"Python programming language\")",
        "lookup_wikipedia(\"quantum entanglement\")",
        "lookup_wikipedia(...)",
        "lookup_wikipedia(topic, timeout = 15)",
        "lookup_wikipedia(topic: str, timeout: int = 15)"
      ],
      "inputs": [],
      "outputs": [
        "`lookup_wikipedia(...)` - returns a plain-text block starting with `\"Wikipedia - <article title>\"` followed by the article extract (up to 400 words). Returns `\"No Wikipedia data found for '<topic>'\"` when no matching article is found. Skips disambiguation pages automatically and tries the next candidate."
      ]
    }
  ]
}
