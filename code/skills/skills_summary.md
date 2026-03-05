# Skills Summary

Single JSON payload for orchestration planning.

{
  "schema_version": "1.0",
  "skills_root": "code/skills",
  "skills": [
    {
      "skill_name": "DateTime Skill",
      "relative_path": "code/skills/DateTime/skill.md",
      "purpose": "Return current date and current time as separate values.",
      "module": "code/skills/DateTime/datetime_skill.py",
      "functions": [
        "get_datetime_data()"
      ],
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
      "purpose": "Provide safe workspace-constrained file access for write, append, read, and listing operations.",
      "module": "code/skills/FileAccess/file_access_skill.py",
      "functions": [
        "append_text_file(file_path: str, text: str)",
        "execute_file_instruction(\"append done to file ./data/content.txt\")",
        "execute_file_instruction(\"create file abc.csv and write header1,header2 into it\")",
        "execute_file_instruction(\"read file ./data/content.txt\")",
        "execute_file_instruction(\"write hello world to file x.txt\")",
        "execute_file_instruction(user_prompt: str)",
        "list_data_files()",
        "read_text_file(file_path: str, max_chars: int = 8000)",
        "write_text_file(file_path: str, text: str)"
      ],
      "inputs": [
        "`file_path`: target file path.",
        "`text`: content to write or append.",
        "`user_prompt`: natural-language instruction for command parsing.",
        "Typical trigger phrases:",
        "`create file <name>`",
        "`write ... to file <path>`",
        "`append ... to file <path>`",
        "`read file <path>`",
        "`write ... in CSV format`"
      ],
      "outputs": [
        "Returns status messages for write/append/list operations.",
        "Returns file content for read operations.",
        "Returns parse guidance when instruction intent/path cannot be resolved."
      ]
    },
    {
      "skill_name": "Memory Skill",
      "relative_path": "code/skills/Memory/skill.md",
      "purpose": "Persist user-stated facts, preferences, and project context across sessions so the agent can recall relevant background in future conversations.",
      "module": "code/skills/Memory/memory_skill.py",
      "functions": [
        "extract_environment_facts(...)",
        "extract_environment_facts(user_prompt: str)",
        "get_memory_store_text()",
        "recall_relevant_memories(\"what is our workspace path\")",
        "recall_relevant_memories(...)",
        "recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)",
        "store_prompt_memories(\"Our workspace path is c:/Util/GithubRepos/MiniAgentFramework\")",
        "store_prompt_memories(...)",
        "store_prompt_memories(user_prompt: str)"
      ],
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
        "`store_prompt_memories(...)` returns a status string describing what was stored.",
        "`recall_relevant_memories(...)` returns a formatted, ranked memory recall string.",
        "`get_memory_store_text()` returns the full text content of the memory store file."
      ]
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "functions": [
        "get_system_info_string()"
      ],
      "inputs": [
        "`get_system_info_string()`",
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
        "`get_system_info_string()` returns a single string, for example:",
        "`System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`"
      ]
    },
    {
      "skill_name": "WebExtract Skill",
      "relative_path": "code/skills/WebExtract/skill.md",
      "purpose": "Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.",
      "module": "code/skills/WebExtract/web_extract_skill.py",
      "functions": [
        "fetch_page_text(\"https://example.com/article\", max_words=400)",
        "fetch_page_text(...)",
        "fetch_page_text(url, max_words, timeout_seconds)",
        "fetch_page_text(url: str, max_words: int = 400, timeout_seconds: int = 15)"
      ],
      "inputs": [
        "`fetch_page_text(url, max_words, timeout_seconds)`",
        "`url`: full HTTP/HTTPS URL to fetch (required)",
        "`max_words`: maximum words of body text to return, 50\u2013800, default 400",
        "`timeout_seconds`: network timeout, 5\u201360, default 15"
      ],
      "outputs": [
        "`fetch_page_text(...)` returns a plain string containing:",
        "The readable prose text extracted from the page body, up to `max_words` words.",
        "`...[truncated]` appended if the content was cut.",
        "A descriptive error string starting with `\"Error:\"` if the fetch or extraction failed."
      ]
    },
    {
      "skill_name": "WebSearch Skill",
      "relative_path": "code/skills/WebSearch/skill.md",
      "purpose": "Search the web using DuckDuckGo (no API key required) and return a ranked list of results with title, URL, and snippet. Pure Python \u2014 no external service accounts needed.",
      "module": "code/skills/WebSearch/web_search_skill.py",
      "functions": [
        "search_web(...)",
        "search_web(query, max_results, timeout_seconds)",
        "search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)",
        "search_web_text(\"Python 3.14 release notes\", max_results=3)",
        "search_web_text(...)",
        "search_web_text(query, max_results, timeout_seconds)",
        "search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)"
      ],
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
    }
  ]
}
