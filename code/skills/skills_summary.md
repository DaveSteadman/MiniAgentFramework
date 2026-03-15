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
      "purpose": "Provide safe workspace-constrained file access for write, append, read, and listing operations.",
      "module": "code/skills/FileAccess/file_access_skill.py",
      "trigger_keyword": "",
      "functions": [
        "append_text_file(file_path: str, text: str)",
        "execute_file_instruction(\"append done to file ./data/content.txt\")",
        "execute_file_instruction(\"create file abc.csv and write header1,header2 into it\")",
        "execute_file_instruction(\"read file ./data/content.txt\")",
        "execute_file_instruction(\"write hello world to file x.txt\")",
        "execute_file_instruction(\"write the system information to ./data/<name>.csv\")",
        "execute_file_instruction(user_prompt: str)",
        "list_data_files()",
        "read_text_file(file_path: str, max_chars: int = 8000)",
        "write_text_file(file_path: str, text: str)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`file_path`: target file path.",
        "`text`: content to write or append.",
        "`user_prompt`: natural-language instruction for command parsing.",
        "Typical trigger phrases:",
        "`create file <name>`",
        "`write ... to file <path>`",
        "`append ... to file <path>`",
        "`read file <path>`",
        "`write the system information to <path>.csv`",
        "`write ... in CSV format`"
      ],
      "outputs": [
        "Returns status messages for write/append/list operations.",
        "Writing a SystemInfo string to a `.csv` file converts it to `key,value` CSV rows automatically.",
        "Returns file content for read operations.",
        "Returns parse guidance when instruction intent/path cannot be resolved."
      ]
    },
    {
      "skill_name": "KoreAnalysis Skill",
      "relative_path": "code/skills/KoreAnalysis/skill.md",
      "purpose": "Read already-mined content from `01-Mine` and produce a structured daily intelligence summary saved to `02-Analysis`.",
      "module": "code/skills/KoreAnalysis/kore_analysis_skill.py",
      "trigger_keyword": "KoreAnalysis",
      "functions": [
        "create_daily_summary(domain, date=\"\", topic=\"\")"
      ],
      "planner_tools": [
        {
          "name": "kore_analysis.create_daily_summary",
          "function": "create_daily_summary",
          "description": "Read already-mined KoreMine content from the 01-Mine stage and produce a saved daily analysis in the 02-Analysis stage. Use this directly for KoreAnalysis tasks.",
          "parameters": {
            "type": "object",
            "properties": {
              "domain": {
                "type": "string",
                "description": "Research domain label that matches the prior KoreMine run."
              },
              "date": {
                "type": "string",
                "description": "Analysis date as YYYY-MM-DD, today, yesterday, or empty for today."
              },
              "topic": {
                "type": "string",
                "description": "Optional framing guidance for the analysis output."
              }
            },
            "required": [
              "domain"
            ]
          },
          "module": "code/skills/KoreAnalysis/kore_analysis_skill"
        }
      ],
      "primary_tool": "kore_analysis.create_daily_summary",
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "KoreMine Skill",
      "relative_path": "code/skills/KoreMine/skill.md",
      "purpose": "Mine web content (direct URLs or DuckDuckGo searches) and save raw results in `webresearch/01-Mine/<domain>/yyyy/mm/dd/`. Does not analyse, summarise, or produce reports.",
      "module": "code/skills/KoreMine/kore_mine_skill.py",
      "trigger_keyword": "KoreMine",
      "functions": [
        "mine_search(query, domain, max_results=5, fetch_content=True, content_words=600)",
        "mine_search_deep(\"UK politics March 2026\", \"GeneralNews\", target_articles=8)",
        "mine_search_deep(query, domain, max_results=10, max_articles_per_result=2, min_words=250, content_words=1500, target_articles=5)",
        "mine_url(url, domain, slug=None, max_words=1200)"
      ],
      "planner_tools": [
        {
          "name": "kore_mine.search",
          "function": "mine_search",
          "description": "Run a DuckDuckGo search for a research topic and save the raw results into the KoreMine 01-Mine stage. Default tool for KoreMine tasks.",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query using human-readable month/year phrasing."
              },
              "domain": {
                "type": "string",
                "description": "Research domain label used for saved output folders."
              },
              "max_results": {
                "type": "number",
                "description": "Number of search results to collect; default 5."
              },
              "fetch_content": {
                "type": "boolean",
                "description": "Whether to fetch and save article body previews for each result."
              },
              "content_words": {
                "type": "number",
                "description": "Approximate word limit for each fetched result body."
              }
            },
            "required": [
              "query",
              "domain"
            ]
          },
          "module": "code/skills/KoreMine/kore_mine_skill"
        },
        {
          "name": "kore_mine.search_deep",
          "function": "mine_search_deep",
          "description": "Run a deeper KoreMine search that follows result pages and saves individual articles. Use when the user explicitly asks for deep mining or broader article collection.",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query using human-readable month/year phrasing."
              },
              "domain": {
                "type": "string",
                "description": "Research domain label used for saved output folders."
              },
              "max_results": {
                "type": "number",
                "description": "Maximum top-level search results to inspect."
              },
              "max_articles_per_result": {
                "type": "number",
                "description": "Maximum child articles to follow from each index page."
              },
              "min_words": {
                "type": "number",
                "description": "Minimum prose threshold used to distinguish article pages from index pages."
              },
              "content_words": {
                "type": "number",
                "description": "Approximate word limit for each saved article body."
              },
              "target_articles": {
                "type": "number",
                "description": "Stop once this many articles have been saved."
              }
            },
            "required": [
              "query",
              "domain"
            ]
          },
          "module": "code/skills/KoreMine/kore_mine_skill"
        },
        {
          "name": "kore_mine.url",
          "function": "mine_url",
          "description": "Fetch a single URL and save its extracted content into the KoreMine 01-Mine stage.",
          "parameters": {
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "description": "Full article URL to fetch and mine."
              },
              "domain": {
                "type": "string",
                "description": "Research domain label used for saved output folders."
              },
              "slug": {
                "type": "string",
                "description": "Optional filename slug override."
              },
              "max_words": {
                "type": "number",
                "description": "Approximate word limit for extracted body text."
              }
            },
            "required": [
              "url",
              "domain"
            ]
          },
          "module": "code/skills/KoreMine/kore_mine_skill"
        }
      ],
      "primary_tool": "kore_mine.search",
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "KoreReport Skill",
      "relative_path": "code/skills/KoreReport/skill.md",
      "purpose": "Read an `analysis.md` produced by KoreAnalysis and render it as a polished, self-contained HTML report saved to `03-Presentation`. All templating and Markdown-to-HTML conversion is handled internally.",
      "module": "code/skills/KoreReport/kore_report_skill.py",
      "trigger_keyword": "KoreReport",
      "functions": [
        "get_analysis_text(domain, date=\"\")",
        "get_report_html(domain, date=\"\")",
        "list_reports(domain, max_days=7)",
        "save_html_report(domain, date=\"\", template=\"default\")"
      ],
      "planner_tools": [
        {
          "name": "kore_report.save_html_report",
          "function": "save_html_report",
          "description": "Read a saved KoreAnalysis analysis.md file and render it to a polished HTML report saved in the 03-Presentation stage. Use this for KoreReport tasks.",
          "parameters": {
            "type": "object",
            "properties": {
              "domain": {
                "type": "string",
                "description": "Research domain label that matches the prior KoreMine and KoreAnalysis runs."
              },
              "date": {
                "type": "string",
                "description": "Report date as YYYY-MM-DD, today, yesterday, or empty for today."
              },
              "template": {
                "type": "string",
                "description": "Report template name; currently default or dark."
              }
            },
            "required": [
              "domain"
            ]
          },
          "module": "code/skills/KoreReport/kore_report_skill"
        }
      ],
      "primary_tool": "kore_report.save_html_report",
      "inputs": [],
      "outputs": []
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
      "skill_name": "PageAssess Skill",
      "relative_path": "code/skills/PageAssess/skill.md",
      "purpose": "Fetch a URL, classify whether it is an article page or an index/listing page, and return a",
      "module": "code/skills/PageAssess/page_assess_skill.py",
      "trigger_keyword": "",
      "functions": [
        "assess_page(...)",
        "assess_page(url, topic, max_links)",
        "assess_page(url: str, topic: str = \"\", max_links: int = 10)"
      ],
      "planner_tools": [],
      "primary_tool": "",
      "inputs": [
        "`assess_page(url, topic, max_links)`",
        "`url`: full HTTP/HTTPS URL to assess (required)",
        "`topic`: optional topic string to filter and rank returned links by word-overlap relevance",
        "`max_links`: maximum article-candidate links to return, 1\u201320, default 10"
      ],
      "outputs": [
        "`page_type` is one of:",
        "`\"article\"` - substantial prose content (\u2265 300 words, \u2264 4 links per 100 words)",
        "`\"index\"` - listing/aggregation page (< 150 words, or \u2265 7 links per 100 words)",
        "`\"mixed\"` - some content plus significant navigation (common on news section pages)",
        "`word_count`: prose words extracted after noise removal and deduplication",
        "`article_links`: sorted by `topic` match score when `topic` provided; otherwise page order",
        "On failure: `{\"error\": \"description of what went wrong\"}` - never raises"
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
      "skill_name": "WebExtract Skill",
      "relative_path": "code/skills/WebExtract/skill.md",
      "purpose": "Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.",
      "module": "code/skills/WebExtract/web_extract_skill.py",
      "trigger_keyword": "",
      "functions": [
        "fetch_page_text(\"https://example.com/article\", max_words=400)",
        "fetch_page_text(...)",
        "fetch_page_text(url, max_words, timeout_seconds)",
        "fetch_page_text(url: str, max_words: int = 400, timeout_seconds: int = 15)"
      ],
      "planner_tools": [],
      "primary_tool": "",
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
      "skill_name": "WebResearchOutput Skill",
      "relative_path": "code/skills/WebResearchOutput/skill.md",
      "purpose": "Dispatches rendered HTML reports from the `03-Presentation` research stage to external destinations. This skill handles **delivery mechanics only** - HTML rendering and template styling are handled entirely by **KoreReport**.",
      "module": "code/skills/WebResearchOutput/web_research_output_skill.py",
      "trigger_keyword": "",
      "functions": [
        "list_reports(domain, max_days=7)",
        "send_report_email(domain, date=\"\", list_name=\"default\", subject=\"\")"
      ],
      "planner_tools": [
        {
          "name": "web_research_output.send_report_email",
          "function": "send_report_email",
          "description": "Send a saved KoreReport HTML report by email to a configured mailing list.",
          "parameters": {
            "type": "object",
            "properties": {
              "domain": {
                "type": "string",
                "description": "Research domain label used by the report."
              },
              "date": {
                "type": "string",
                "description": "Report date as YYYY-MM-DD, today, yesterday, or empty for today."
              },
              "list_name": {
                "type": "string",
                "description": "Configured mailing list key in controldata/email_config.json."
              },
              "subject": {
                "type": "string",
                "description": "Optional email subject line override."
              }
            },
            "required": [
              "domain"
            ]
          },
          "module": "code/skills/WebResearchOutput/web_research_output_skill"
        },
        {
          "name": "web_research_output.list_reports",
          "function": "list_reports",
          "description": "List available rendered HTML reports in the 03-Presentation stage for a domain.",
          "parameters": {
            "type": "object",
            "properties": {
              "domain": {
                "type": "string",
                "description": "Research domain label used by the report."
              },
              "max_days": {
                "type": "number",
                "description": "Maximum number of dated report entries to return."
              }
            },
            "required": [
              "domain"
            ]
          },
          "module": "code/skills/WebResearchOutput/web_research_output_skill"
        }
      ],
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
    }
  ]
}
