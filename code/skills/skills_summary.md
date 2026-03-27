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
      "triggers": [
        "calculate",
        "compute",
        "what is X",
        "evaluate",
        "Powers, factorials, primes, fibonacci, sequences, series",
        "Sum, product, average, mean, median, mode, standard deviation",
        "Compound interest, percentage, ratio, conversion between units",
        "Multiplication tables, squares/cubes tables, truth tables, lookup tables",
        "print a table",
        "generate a list",
        "produce a list",
        "list all X",
        "first N of",
        "Identity matrix, Pascal's triangle, any structured numeric output",
        "how many times",
        "count the",
        "Reverse, sort, check for palindromes, anagram detection",
        "Any prompt asking to inspect or transform a string value",
        "convert X to binary/hex/octal/decimal",
        "ASCII codes, encoding lookups",
        "Collatz sequence, any recurrence relation",
        "first N",
        "up to N",
        "for each",
        "from 1 to N"
      ],
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
      ],
      "param_descriptions": {
        "run_python_snippet": {
          "code": "a complete, self-contained Python snippet as a string. Must use `print()` for all output."
        }
      }
    },
    {
      "skill_name": "DateTime Skill",
      "relative_path": "code/skills/DateTime/skill.md",
      "purpose": "Return the current date, time, day name, and month name. Prefer `get_datetime_data()` in all cases - it returns both date and time in a single call. Use `get_day_name()` or `get_month_name()` only when you specifically need just that one value.",
      "module": "code/skills/DateTime/datetime_skill.py",
      "trigger_keyword": "current date, time, day of the week, or month name",
      "triggers": [
        "what is the date",
        "current date",
        "today's date",
        "what time is it",
        "current time",
        "what day is it",
        "what year is it",
        "what month is it",
        "current month",
        "month name",
        "day of the week",
        "day name"
      ],
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
      ],
      "param_descriptions": {}
    },
    {
      "skill_name": "FileAccess Skill",
      "relative_path": "code/skills/FileAccess/skill.md",
      "purpose": "Interface for all file read, write, append, and search operations. All relative paths resolve under `./data/`; a `\"./\"` prefix anchors a path at the workspace root instead. Paths that escape the workspace root are rejected.",
      "module": "code/skills/FileAccess/file_access_skill.py",
      "trigger_keyword": "file",
      "triggers": [
        "write to file",
        "create file",
        "save to file",
        "write page to file",
        "save fetched content to file",
        "write from scratch",
        "write scratch to file",
        "append to file",
        "add to file",
        "read file",
        "show file",
        "open file",
        "contents of",
        "find file",
        "find folder",
        "locate file",
        "search for file",
        "create folder",
        "make folder",
        "create directory",
        "folder exists",
        "does folder exist"
      ],
      "functions": [
        "append_file(\"data/log.txt\", \"new entry\")",
        "append_file(\"data/log.txt\", \"{scratch:codeoutput}\")",
        "append_file(...)",
        "append_file(path, content)",
        "append_file(path: str, content: str)",
        "create_folder(...)",
        "create_folder(path)",
        "create_folder(path: str)",
        "find_files(...)",
        "find_files([\"pulse\"], \"data\")",
        "find_files([\"test\", \"2026\"])",
        "find_files(keywords, search_root = \"\")",
        "find_files(keywords: list[str], search_root: str = \"\")",
        "find_folders(...)",
        "find_folders([\"2026-03\"])",
        "find_folders(keywords, search_root = \"\")",
        "find_folders(keywords: list[str], search_root: str = \"\")",
        "folder_exists(...)",
        "folder_exists(path)",
        "folder_exists(path: str)",
        "read_file(...)",
        "read_file(path, max_chars = 8000)",
        "read_file(path: str, max_chars: int = 8000)",
        "read_file(path=\"data/log.txt\")",
        "write_file(\"data/result.txt\", \"{scratch:searchresult}\")",
        "write_file(\"notes/meeting.txt\", \"Discuss project timeline\")",
        "write_file(...)",
        "write_file(path, content)",
        "write_file(path: str, content: str)",
        "write_from_scratch(...)",
        "write_from_scratch(scratch_key, path)",
        "write_from_scratch(scratch_key: str, path: str)"
      ],
      "inputs": [],
      "outputs": [
        "`write_file(...)` - returns `\"Wrote data/filename.txt\"` on success, or `\"Error: ...\"` on failure.",
        "`append_file(...)` - returns `\"Appended data/filename.txt\"` on success, or `\"Error: ...\"` on failure.",
        "`read_file(...)` - returns the file content as a string, or `\"File not found: ...\"` if the file does not exist.",
        "`find_files(...)` - returns a newline-separated list of matching workspace-relative paths, or a `\"No files found...\"` message.",
        "`find_folders(...)` - returns a newline-separated list of matching workspace-relative paths, or a `\"No folders found...\"` message.",
        "`write_from_scratch(...)` - returns `\"Wrote data/file.md (12345 chars from scratch key '_tc_r5_fetch_page_text')\"` on success, or `\"Error: ...\"` on failure.",
        "`create_folder(...)` - returns `\"Created folder: path\"` or `\"Folder already exists: path\"`, or `\"Error: ...\"` on failure.",
        "`folder_exists(...)` - returns `\"yes\"` or `\"no\"`."
      ],
      "param_descriptions": {
        "write_from_scratch": {
          "scratch_key": "scratchpad key holding the content to write, e.g. `\"_tc_r5_fetch_page_text\"` (the key shown in a truncation notice). Reads the stored value directly without requiring a separate `scratch_load` call.",
          "path": "destination path; same resolution rules as `write_file`."
        },
        "create_folder": {
          "path": "path of the directory to create, resolved under `data/`, e.g. `\"webresearch/01-Mine/2026-03-22\"`. Creates all missing parent directories. Safe to call if the folder already exists."
        },
        "folder_exists": {
          "path": "workspace-relative path to check."
        },
        "write_file": {
          "path": "workspace-relative path. A bare name like `\"x.txt\"` resolves to `data/x.txt`. A path starting with `\"./\"` resolves from workspace root.",
          "content": "content to write. Overwrites the file if it exists. Supports `{scratch:key}` token substitution - use `\"{scratch:mykey}\"` to write scratchpad content directly without calling `scratch_load` first."
        },
        "append_file": {
          "path": "same path rules as `write_file`.",
          "content": "content to append. A newline is added automatically if missing. Supports `{scratch:key}` token substitution - use `\"{scratch:mykey}\"` to append scratchpad content directly."
        },
        "read_file": {
          "path": "same path rules as `write_file`.",
          "max_chars": "maximum characters to return; content is truncated with `[truncated]` if exceeded."
        },
        "find_files": {
          "keywords": "list of case-insensitive fragments that must ALL appear in the file name, e.g. `[\"pulse\", \"2026\"]`.",
          "search_root": "workspace-relative directory to restrict the search, e.g. `\"data\"`. Leave empty to search the whole workspace."
        },
        "find_folders": {
          "keywords": "list of case-insensitive fragments that must ALL appear in the folder name.",
          "search_root": "workspace-relative directory to restrict the search. Leave empty to search the whole workspace."
        }
      }
    },
    {
      "skill_name": "Memory Skill",
      "relative_path": "code/skills/Memory/skill.md",
      "purpose": "Persist and recall durable user-stated facts across sessions - identity, preferences, project context, and environment facts. A newer fact on the same subject supersedes the older one. Do not store questions, commands, or ephemeral data such as current time or system stats. Facts persist in `memory_store.json` with category, timestamps, and access tracking.",
      "module": "code/skills/Memory/memory_skill.py",
      "trigger_keyword": "memory",
      "triggers": [
        "remember",
        "store this",
        "save this fact",
        "note that",
        "recall",
        "what do you know about",
        "do you remember",
        "my name is",
        "I prefer",
        "our project is",
        "the default model is",
        "show memory",
        "memory store",
        "what have you stored"
      ],
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
      ],
      "param_descriptions": {
        "store_prompt_memories": {
          "user_prompt": "raw user text to extract facts from and store."
        },
        "recall_relevant_memories": {
          "user_prompt": "current prompt used as the relevance query.",
          "limit": "maximum number of memories to return.",
          "min_score": "minimum token-overlap relevance threshold; lower values return more results."
        },
        "extract_environment_facts": {
          "user_prompt": "raw user text to inspect for environment-specific facts only."
        }
      }
    },
    {
      "skill_name": "Scratchpad Skill",
      "relative_path": "code/skills/Scratchpad/skill.md",
      "purpose": "Store and retrieve named working values within a session so that bulk data returned by other skills",
      "module": "code/skills/Scratchpad/scratchpad_skill.py",
      "trigger_keyword": "scratchpad",
      "triggers": [
        "save to scratchpad",
        "store in scratchpad",
        "park this result",
        "load from scratchpad",
        "retrieve from scratchpad",
        "get scratchpad value",
        "list scratchpad",
        "what is in the scratchpad",
        "dump scratchpad",
        "show scratchpad contents",
        "inspect scratchpad",
        "debug scratchpad",
        "delete from scratchpad",
        "clear scratchpad key",
        "search scratchpad",
        "find scratchpad keys containing",
        "which scratchpad keys have",
        "peek at scratchpad",
        "show context around",
        "find text in scratchpad key",
        "query scratchpad",
        "ask scratchpad",
        "extract from scratchpad",
        "filter scratchpad",
        "run query on scratchpad key"
      ],
      "functions": [
        "scratch_delete(\"webresult\")",
        "scratch_delete(...)",
        "scratch_delete(key)",
        "scratch_delete(key: str)",
        "scratch_dump()",
        "scratch_list()",
        "scratch_load(\"webresult\")",
        "scratch_load(...)",
        "scratch_load(key)",
        "scratch_load(key: str)",
        "scratch_peek(\"webresult\", \"content\", 100)",
        "scratch_peek(...)",
        "scratch_peek(key, substring)",
        "scratch_peek(key, substring, context_chars = 250)",
        "scratch_peek(key: str, substring: str, context_chars: int = 250)",
        "scratch_query(\"racedata\", \"List only Ferrari wins\", \"ferrari_wins\")",
        "scratch_query(\"racedata\", \"Which drivers won at Monaco?\")",
        "scratch_query(...)",
        "scratch_query(key, query, save_result_key = \"\")",
        "scratch_query(key, question)",
        "scratch_query(key: str, query: str, save_result_key: str = \"\")",
        "scratch_save(\"webresult\", \"page content here...\")",
        "scratch_save(...)",
        "scratch_save(key, value)",
        "scratch_save(key: str, value: str)",
        "scratch_search(\"error\")",
        "scratch_search(...)",
        "scratch_search(substring)",
        "scratch_search(substring: str)"
      ],
      "inputs": [],
      "outputs": [
        "`scratch_save(...)` - returns `\"Saved to scratchpad key '<key>' (N chars)\"` on success, or `\"Error: ...\"`.",
        "`scratch_load(...)` - returns the stored string value, or an error message if the key is not found.",
        "`scratch_list()` - returns a formatted list of active keys and their sizes, or `\"Scratchpad is empty.\"`.",
        "`scratch_dump()` - returns every key followed by its full stored value. Use to inspect scratchpad contents for debugging.",
        "`scratch_delete(...)` - returns confirmation or `\"Scratchpad key '<key>' not found - nothing deleted.\"`.",
        "`scratch_search(...)` - returns a formatted list of matching key names and sizes, or `\"No scratchpad keys contain the substring '<text>'.\"` when no match is found.",
        "`scratch_peek(...)` - returns `[Match in 'key' at char N / M total]` followed by the surrounding text with `>>>match<<<` highlighting, or an error string when the key or substring is not found.",
        "`scratch_query(...)` - returns the compact extracted answer from the isolated LLM call, or `\"Not found in content.\"` when the query cannot be answered from the stored value.  When `save_result_key` is provided, prepends `[Result saved to '<key>']` to the output."
      ],
      "param_descriptions": {
        "scratch_save": {
          "key": "short alphanumeric identifier for the value, e.g. `\"webresult\"` or `\"step1_output\"`. Letters, digits, and underscores only. Stored lowercased.",
          "value": "the string content to store. Overwrites any previous value at that key."
        },
        "scratch_load": {
          "key": "the key to retrieve. Returns an error message when the key does not exist."
        },
        "scratch_delete": {
          "key": "the key to remove from the scratchpad."
        },
        "scratch_search": {
          "substring": "case-insensitive text to search for within stored values. Returns all keys whose value contains the substring."
        },
        "scratch_peek": {
          "key": "the scratchpad key to inspect.",
          "substring": "case-insensitive text to locate within the stored value.",
          "context_chars": "characters to include before and after the match."
        },
        "scratch_query": {
          "key": "the scratchpad key whose full content will be used as input.",
          "query": "natural-language question or instruction to apply to the stored content.",
          "save_result_key": "if provided, the extracted answer is also saved to this scratchpad key."
        }
      }
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information including OS name, Python and Ollama versions, RAM usage, and disk usage. Use this for any prompt about the machine, hardware, runtime environment, available resources, or version details. Do not use this for web or file queries.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "trigger_keyword": "system info, RAM or disk space, available memory, or OS and runtime version details",
      "triggers": [
        "system info",
        "system health",
        "machine info",
        "specs",
        "resource usage",
        "RAM",
        "memory usage",
        "available memory",
        "how much RAM",
        "disk space",
        "free space",
        "disk available",
        "storage",
        "Python version",
        "Ollama version",
        "what OS",
        "operating system",
        "can we fit",
        "do we have enough",
        "is there enough space"
      ],
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
      ],
      "param_descriptions": {}
    },
    {
      "skill_name": "TaskManagement Skill",
      "relative_path": "code/skills/TaskManagement/skill.md",
      "purpose": "Create, query, update, enable, disable, and delete scheduled tasks stored as JSON files in `controldata/schedules/`. Each task defines a schedule and a prompt string that the scheduler runs automatically on each firing.",
      "module": "code/skills/TaskManagement/task_management_skill.py",
      "trigger_keyword": "task",
      "triggers": [
        "create task",
        "add task",
        "schedule a task",
        "list tasks",
        "show tasks",
        "what tasks are scheduled",
        "enable task",
        "disable task",
        "turn on task",
        "turn off task",
        "update task",
        "change schedule",
        "delete task",
        "remove task"
      ],
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
      ],
      "param_descriptions": {
        "get_task": {
          "name": "exact task name (case-insensitive)."
        },
        "create_task": {
          "name": "unique task name; alphanumeric, hyphens, underscores only.",
          "schedule": "interval as a plain integer string, e.g. `\"60\"` = every 60 minutes; OR a daily wall-clock time as `\"HH:MM\"`, e.g. `\"08:30\"` = every day at 08:30.",
          "prompt": "the natural-language instruction the scheduler will run on each firing."
        },
        "set_task_enabled": {
          "name": "task name.",
          "enabled": "`true` to enable, `false` to disable."
        },
        "set_task_schedule": {
          "name": "task name.",
          "schedule": "same format as `create_task`: integer minutes or `\"HH:MM\"`."
        },
        "set_task_prompt": {
          "name": "task name.",
          "prompt": "replacement prompt text."
        },
        "delete_task": {
          "name": "name of the task to permanently remove."
        }
      }
    },
    {
      "skill_name": "WebFetch Skill",
      "relative_path": "code/skills/WebFetch/skill.md",
      "purpose": "Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.",
      "module": "code/skills/WebFetch/web_fetch_skill.py",
      "trigger_keyword": "fetch",
      "triggers": [
        "fetch the page",
        "read the content of",
        "get the article from",
        "open the URL",
        "read this URL",
        "what does the page say"
      ],
      "functions": [
        "fetch_page_text(\"https://example.com/asyncio-guide\", query=\"summarise the key asyncio concepts\")",
        "fetch_page_text(url, max_words, timeout_seconds, query)",
        "fetch_page_text(url: str, max_words: int = 1000, timeout_seconds: int = 15, query: str | None = None)"
      ],
      "inputs": [],
      "outputs": [
        "When `query` is None: the readable body text extracted from the page, up to `max_words` words.",
        "When `query` is set: a concise LLM-extracted answer targeted at the query, or `\"Not found on this page.\"`",
        "A string beginning with `\"Error:\"` if the fetch or parse failed. Never raises."
      ],
      "param_descriptions": {
        "fetch_page_text": {
          "url": "full HTTP or HTTPS URL to fetch. Local paths and ftp:// are rejected.",
          "max_words": "maximum words of body prose to return (range 50-4000).",
          "timeout_seconds": "network timeout in seconds (range 5-60).",
          "query": "when provided, runs an isolated LLM extraction pass and returns only the facts relevant to the query. Use when you know exactly what you are looking for on the page."
        }
      }
    },
    {
      "skill_name": "WebResearch Skill",
      "relative_path": "code/skills/WebResearch/skill.md",
      "purpose": "Search the web, visit multiple relevant pages, extract the useful text, optionally follow promising links, and return a compact evidence-led research bundle.",
      "module": "code/skills/WebResearch/web_research_skill.py",
      "trigger_keyword": "",
      "triggers": [
        "research this",
        "investigate",
        "look into",
        "search and examine",
        "find the answer across multiple pages",
        "follow the links",
        "gather evidence from the web"
      ],
      "functions": [
        "research_traverse(\"What changed in Python 3.14 packaging guidance?\", max_pages=8, max_hops=1)",
        "research_traverse(\"Which Ferrari drivers have won the Monaco Grand Prix?\")",
        "research_traverse(query, max_search_results = 5, max_pages = 6, max_hops = 1, same_domain_only_for_hops = True, timeout_seconds = 15, max_words_per_page = 450, max_evidence_quotes = 3)",
        "research_traverse(query: str, max_search_results: int = 5, max_pages: int = 6, max_hops: int = 1, same_domain_only_for_hops: bool = True, timeout_seconds: int = 15, max_words_per_page: int = 450, max_evidence_quotes: int = 3)"
      ],
      "inputs": [],
      "outputs": [
        "returns a dict with:",
        "`query` - original query",
        "`summary` - short synthesis of the strongest evidence found",
        "`answer_confidence` - `high`, `medium`, or `low`",
        "`visited_count` - number of fetched pages",
        "`seed_results` - initial search results used to seed the traversal",
        "`best_pages` - compact list of the most relevant pages with URL, title, score, and evidence snippets",
        "`exploration_log` - per-page log showing what was visited and why",
        "`unvisited_candidates` - discovered but not visited URLs",
        "`full_report` - larger text block suitable for scratchpad storage"
      ],
      "param_descriptions": {
        "research_traverse": {
          "query": "the research question or investigation prompt.",
          "max_search_results": "number of search results to seed the frontier from.",
          "max_pages": "maximum total number of pages to visit.",
          "max_hops": "how many link-following hops beyond the initial search results are allowed.",
          "same_domain_only_for_hops": "when following links found inside pages, stay on the same domain unless set false.",
          "timeout_seconds": "network timeout per fetch.",
          "max_words_per_page": "truncate extracted page text per page to control size.",
          "max_evidence_quotes": "number of best evidence snippets to keep per useful page."
        }
      }
    },
    {
      "skill_name": "WebSearch Skill",
      "relative_path": "code/skills/WebSearch/skill.md",
      "purpose": "Search the web using DuckDuckGo and return ranked results with title, URL, and snippet. No API key required. Use `search_web_text` for direct synthesis - results come back as formatted text ready to read inline. Use `search_web` when you need to iterate over individual result fields (url, title, snippet) programmatically or pass them selectively to another skill. This skill only returns results - it does not persist or save anything.",
      "module": "code/skills/WebSearch/web_search_skill.py",
      "trigger_keyword": "search",
      "triggers": [
        "search the web for",
        "find information about",
        "look up",
        "what is the latest news on",
        "search for",
        "find recent"
      ],
      "functions": [
        "search_web(\"Eiffel Tower height\")",
        "search_web(...)",
        "search_web(query, max_results = 5, timeout_seconds = 15)",
        "search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)",
        "search_web_text(\"Python 3.14 release notes\")",
        "search_web_text(\"Python 3.14 release notes\", max_results=3)",
        "search_web_text(...)",
        "search_web_text(query, max_results = 5, timeout_seconds = 15)",
        "search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)"
      ],
      "inputs": [],
      "outputs": [
        "`search_web(...)` - returns `list[dict]`, each entry with `rank` (int), `title` (str), `url` (str), `snippet` (str). On error: single-entry list with `rank=0` and `snippet` describing the failure.",
        "`search_web_text(...)` - returns a plain-text formatted block with rank, title, URL, and snippet per result. Ready for direct LLM consumption."
      ],
      "param_descriptions": {
        "search_web": {
          "query": "search query string.",
          "max_results": "number of results to return, 1-10.",
          "timeout_seconds": "network timeout in seconds, 5-30."
        },
        "search_web_text": {
          "query": "search query string.",
          "max_results": "number of results to return, 1-10.",
          "timeout_seconds": "network timeout in seconds, 5-30."
        }
      }
    },
    {
      "skill_name": "Wikipedia Skill",
      "relative_path": "code/skills/Wikipedia/skill.md",
      "purpose": "Look up a topic on Wikipedia and return a plain-text article summary. Use this for authoritative factual reference data about a person, place, concept, event, or technology. For current news or live data, use WebSearch instead.",
      "module": "code/skills/Wikipedia/wikipedia_skill.py",
      "trigger_keyword": "wikipedia",
      "triggers": [
        "what is",
        "tell me about",
        "who is",
        "look up on Wikipedia",
        "Wikipedia article",
        "background on",
        "history of",
        "definition of",
        "bio",
        "biography",
        "life of",
        "biography of"
      ],
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
      ],
      "param_descriptions": {
        "lookup_wikipedia": {
          "topic": "subject to look up: a name, term, acronym, or short phrase.",
          "timeout": "network timeout in seconds."
        }
      }
    }
  ]
}
