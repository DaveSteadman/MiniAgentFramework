# Skills Summary

Single JSON payload for orchestration planning.

{
  "schema_version": "1.0",
  "skills_root": "code/skills",
  "skills": [
    {
      "skill_name": "CodeExecute Skill",
      "relative_path": "code/skills/CodeExecute/skill.md",
      "purpose": "Execute a Python code snippet in a sandboxed environment and return the captured stdout as a string - use when the user requests computed or generated data (sequences, tables, calculations) that no other skill can produce. Only Python stdlib modules are available (math, itertools, collections, datetime, json, csv, re, statistics, etc.) - third-party packages such as numpy, pandas, sympy, and scipy are not available; always write self-contained stdlib code.",
      "module": "code/skills/CodeExecute/code_execute_skill.py",
      "trigger_keyword": "",
      "functions": [
        "run_python_snippet(code: str)",
        "run_python_snippet(code=\"import math\\nfor i in range(1, 6):\\n    print(i, math.factorial(i))\")",
        "run_python_snippet(code=\"print('index,prime,fib')\\n# ... full snippet ...\")",
        "run_python_snippet(code=<snippet>)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`run_python_snippet(code: str)`",
        "`code`: a complete, self-contained Python snippet.",
        "The snippet must use print() to emit all output - the return value of the last",
        "Imports are restricted to a safe stdlib whitelist when sandbox is enabled (default): math, itertools, collections, csv, io,",
        "os, sys, subprocess, open, eval, exec, and file I/O are blocked when sandbox is enabled.",
        "Sandbox state can be toggled at runtime with `/sandbox on|off`.",
        "Execution timeout: 15 seconds."
      ],
      "outputs": [
        "Captured stdout as a plain string.",
        "If the snippet raises an exception or produces no output, returns an error string starting"
      ]
    },
    {
      "skill_name": "DateTime Skill",
      "relative_path": "code/skills/DateTime/skill.md",
      "purpose": "Return current date and current time as separate values.",
      "module": "code/skills/DateTime/datetime_skill.py",
      "trigger_keyword": "",
      "functions": [
        "get_datetime_data()"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`get_datetime_data()`",
        "No arguments."
      ],
      "outputs": [
        "`get_datetime_data()` returns a structured object:",
        "`{ \"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM:SS\" }`"
      ]
    },
    {
      "skill_name": "FileAccess Skill",
      "relative_path": "code/skills/FileAccess/skill.md",
      "purpose": "Provide safe workspace-constrained file access for write, append, read, listing, and name-based search operations.",
      "module": "code/skills/FileAccess/file_access_skill.py",
      "trigger_keyword": "",
      "functions": [
        "append_text_file(file_path: str, text: str)",
        "execute_file_instruction(\"append done to file ./data/content.txt\")",
        "execute_file_instruction(\"read file ./data/content.txt\")",
        "execute_file_instruction(\"write hello world to file x.txt\")",
        "execute_file_instruction(user_prompt: str)",
        "find_files([\"analysis\"])",
        "find_files([\"pulse\"], \"data\")",
        "find_files([\"test\", \"2026\"])",
        "find_files(keywords: list[str], search_root: str = \"\")",
        "find_folders([\"2026-03\"])",
        "find_folders(keywords: list[str], search_root: str = \"\")",
        "list_data_files()",
        "read_text_file(file_path: str, max_chars: int = 8000)",
        "write_text_file(file_path: str, text: str)"
      ],
      "planner_tools": [
        {
          "name": "find_files",
          "function": "find_files",
          "description": "Search the workspace for files whose name contains all of the given keyword fragments. Returns a list of matching relative paths. Use this when you know part of a filename but not the exact path.",
          "parameters": {
            "type": "object",
            "properties": {
              "keywords": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "One or more case-insensitive fragments that must ALL appear in the file name."
              },
              "search_root": {
                "type": "string",
                "description": "Optional workspace-relative directory to restrict the search (e.g. 'data' or 'controldata'). Leave empty to search the whole workspace."
              }
            },
            "required": [
              "keywords"
            ]
          },
          "module": "code/skills/FileAccess/file_access_skill"
        },
        {
          "name": "find_folders",
          "function": "find_folders",
          "description": "Search the workspace for folders whose name contains all of the given keyword fragments. Returns a list of matching relative paths. Use this when you need to locate a directory by partial name.",
          "parameters": {
            "type": "object",
            "properties": {
              "keywords": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "One or more case-insensitive fragments that must ALL appear in the folder name."
              },
              "search_root": {
                "type": "string",
                "description": "Optional workspace-relative directory to restrict the search. Leave empty to search the whole workspace."
              }
            },
            "required": [
              "keywords"
            ]
          },
          "module": "code/skills/FileAccess/file_access_skill"
        }
      ],
      "primary_tool": "find_files",
      "inputs": [
        "`file_path`: target file path.",
        "`text`: content to write or append.",
        "`user_prompt`: natural-language instruction for command parsing.",
        "`keywords`: list of one or more case-insensitive name fragments for find operations - ALL must appear in the name.",
        "`search_root`: optional workspace-relative directory to restrict find searches.",
        "Typical trigger phrases:",
        "`create file <name>`",
        "`write ... to file <path>`",
        "`append ... to file <path>`",
        "`read file <path>`",
        "`find file named <keyword>`",
        "`find folder named <keyword>`",
        "`find files containing <keyword> in <folder>`"
      ],
      "outputs": [
        "Returns status messages for write/append/list operations.",
        "Writing a SystemInfo string to a `.csv` file converts it to `key,value` CSV rows automatically.",
        "Returns file content for read operations.",
        "`find_files` returns a newline-separated list of workspace-relative file paths whose names contain ALL keywords, or a \"not found\" message.",
        "`find_folders` returns a newline-separated list of workspace-relative folder paths whose names contain ALL keywords, or a \"not found\" message.",
        "Returns parse guidance when instruction intent/path cannot be resolved."
      ]
    },
    {
      "skill_name": "Memory Skill",
      "relative_path": "code/skills/Memory/skill.md",
      "purpose": "Persist user-stated facts, preferences, and project context across sessions so the agent can recall relevant background in future conversations.",
      "module": "code/skills/Memory/memory_skill.py",
      "trigger_keyword": "",
      "functions": [
        "extract_environment_facts(...)",
        "extract_environment_facts(user_prompt: str)",
        "get_memory_store_text()",
        "recall_relevant_memories(\"what is our workspace path\")",
        "recall_relevant_memories(...)",
        "recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)",
        "store_prompt_memories(\"Our workspace path is c:/Util/GithubRepos/MiniAgentFramework\")",
        "store_prompt_memories(\"Our workspace path is c:/Util/NewLocation\")",
        "store_prompt_memories(...)",
        "store_prompt_memories(user_prompt: str)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`extract_environment_facts(user_prompt: str)`",
        "`user_prompt`: raw user text to inspect for durable environment facts.",
        "`store_prompt_memories(user_prompt: str)`",
        "`user_prompt`: prompt used for extraction and deduplicated storage.",
        "`recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)`",
        "`user_prompt`: current prompt to use as relevance query.",
        "`limit`: max number of returned memories.",
        "`min_score`: minimum token-overlap relevance threshold.",
        "`get_memory_store_text()`",
        "No arguments."
      ],
      "outputs": [
        "`extract_environment_facts(...)` returns a list of candidate environment-specific facts.",
        "`store_prompt_memories(...)` returns a status string - e.g. \"Stored 1 new memory fact(s).\" or \"Updated 1 existing memory fact(s).\"",
        "`recall_relevant_memories(...)` returns a formatted, ranked memory recall string with categories.",
        "`get_memory_store_text()` returns the full pretty-printed JSON of the memory store."
      ]
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "trigger_keyword": "",
      "functions": [
        "get_system_info_dict()"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`get_system_info_dict()`",
        "No arguments.",
        "Typical trigger phrases (select this skill for any of these concepts):",
        "`system information`, `system info`, `system health`",
        "`machine info`, `runtime info`, `environment information`",
        "`RAM usage`, `RAM available`, `how much RAM`, `available memory`, `used memory`, `memory usage`",
        "`disk usage`, `disk space`, `disk available`, `free disk`, `free space`, `available space`",
        "`can we fit`, `do we have enough space`, `is there enough disk`, `enough room`, `enough storage`",
        "`python version`, `what version of python`, `ollama version`, `what version of ollama`",
        "`what OS`, `operating system`, `what platform`, `what machine`",
        "`show specs`, `show health`, `system stats`, `resource usage`"
      ],
      "outputs": [
        "`get_system_info_dict()` returns a structured dict with individually addressable fields:",
        "`os` (str) - OS name, e.g. `\"Windows\"`",
        "`python_version` (str) - e.g. `\"3.10.11\"`",
        "`ollama_version` (str) - e.g. `\"0.18.0\"`",
        "`ram_used_gb` (float) - RAM in use in GiB, e.g. `30.80`",
        "`ram_available_gb` (float) - RAM free in GiB, e.g. `96.49`",
        "`disk_used_gb` (float) - disk used in GiB, e.g. `937.34`",
        "`disk_available_gb` (float) - disk free in GiB, e.g. `924.72`"
      ]
    },
    {
      "skill_name": "TaskManagement Skill",
      "relative_path": "code/skills/TaskManagement/skill.md",
      "purpose": "Create, query, update, enable, disable, and delete scheduled tasks stored as JSON files in",
      "module": "code/skills/TaskManagement/task_management_skill.py",
      "trigger_keyword": "",
      "functions": [
        "create_task(\"DailyWeather\", \"08:00\", \"Check the weather forecast for today and summarise it.\")",
        "create_task(\"HourlyMemCheck\", \"60\", \"Check free RAM and log it to data/memlog.csv.\")",
        "create_task(name, schedule, prompt)",
        "create_task(name: str, schedule: str, prompt: str)",
        "delete_task(\"OldTask\")",
        "delete_task(name)",
        "delete_task(name: str)",
        "get_task(\"PerformanceHeadroom\")",
        "get_task()",
        "get_task(name)",
        "get_task(name: str)",
        "list_tasks()",
        "set_task_enabled(\"DailyWeather\", True)",
        "set_task_enabled(\"PerformanceHeadroom\", False)",
        "set_task_enabled(name, enabled)",
        "set_task_enabled(name: str, enabled: bool)",
        "set_task_prompt(\"DailyWeather\", \"Get today's weather forecast and temperature for London.\")",
        "set_task_prompt(name, prompt)",
        "set_task_prompt(name: str, prompt: str)",
        "set_task_schedule(\"DailyWeather\", \"07:30\")",
        "set_task_schedule(\"HourlyMemCheck\", \"30\")",
        "set_task_schedule(name, schedule)",
        "set_task_schedule(name: str, schedule: str)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "WebSearch Skill",
      "relative_path": "code/skills/WebSearch/skill.md",
      "purpose": "Search the web using DuckDuckGo (no API key required) and return a ranked list of results with title, URL, and snippet. Pure Python - no external service accounts needed.",
      "module": "code/skills/WebSearch/web_search_skill.py",
      "trigger_keyword": "",
      "functions": [
        "search_web(...)",
        "search_web(query, max_results, timeout_seconds)",
        "search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)",
        "search_web_text(\"Python 3.14 release notes\", max_results=3)",
        "search_web_text(...)",
        "search_web_text(query, max_results, timeout_seconds)",
        "search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`search_web(query, max_results, timeout_seconds)`",
        "`query`: search query string (required)",
        "`max_results`: number of results to return, 1\u201310, default 5",
        "`timeout_seconds`: network timeout, 5\u201330, default 15",
        "`search_web_text(query, max_results, timeout_seconds)`",
        "Same arguments as `search_web`."
      ],
      "outputs": [
        "`search_web(...)` returns a `list[dict]`, each entry containing:",
        "`rank` (int): result position, starting at 1",
        "`title` (str): page title",
        "`url` (str): destination URL",
        "`snippet` (str): short description from DuckDuckGo",
        "On error: a single-entry list with `rank=0` and `snippet` describing the failure.",
        "`search_web_text(...)` returns a plain-text formatted string suitable for direct LLM consumption:"
      ]
    },
    {
      "skill_name": "Wikipedia Skill",
      "relative_path": "code/skills/Wikipedia/skill.md",
      "purpose": "Look up a topic on Wikipedia and return a plain-text article summary. Use this when the LLM needs factual reference data about a person, place, concept, event, or technology - any time it would benefit from an authoritative definition or background.",
      "module": "code/skills/Wikipedia/wikipedia_skill.py",
      "trigger_keyword": "",
      "functions": [
        "lookup_wikipedia(\"Eiffel Tower\")",
        "lookup_wikipedia(\"Marie Curie\")",
        "lookup_wikipedia(\"Python programming language\")",
        "lookup_wikipedia(\"quantum entanglement\")",
        "lookup_wikipedia(topic: str, timeout: int = 15)"
      ],
      "planner_tools": [
        {
          "name": "lookup_wikipedia",
          "function": "lookup_wikipedia",
          "description": "Look up a topic on Wikipedia and return a plain-text article summary. Use this when you need factual reference data about a person, place, concept, event, or technology. Returns the article extract, or 'No Wikipedia data found' when nothing is available.",
          "parameters": {
            "type": "object",
            "properties": {
              "topic": {
                "type": "string",
                "description": "The subject to look up - e.g. 'Python programming language', 'Eiffel Tower', 'quantum entanglement'."
              }
            },
            "required": [
              "topic"
            ]
          },
          "module": "code/skills/Wikipedia/wikipedia_skill"
        }
      ],
      "primary_tool": "lookup_wikipedia",
      "inputs": [
        "`topic`: the subject to look up (required). Can be a name, term, acronym, or short phrase.",
        "`timeout`: network timeout in seconds (optional, default 15)."
      ],
      "outputs": [
        "Returns a plain-text block starting with `Wikipedia - <article title>` followed by the article extract (up to 400 words).",
        "Returns `No Wikipedia data found for '<topic>'` when no matching article exists or no useful extract is available."
      ]
    }
  ]
}
