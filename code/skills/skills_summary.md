# Skills Summary

Single JSON payload for orchestration planning.

{
  "schema_version": "1.0",
  "skills_root": "code/skills",
  "skills": [
    {
      "skill_name": "CodeExecute Skill",
      "relative_path": "code/skills/CodeExecute/skill.md",
      "purpose": "Execute a Python code snippet in a sandboxed environment and return the captured stdout as a string - use when the user requests computed or generated data (sequences, tables, calculations) that no other skill can produce.",
      "module": "code/skills/CodeExecute/code_execute_skill.py",
      "functions": [
        "run_python_snippet(code: str)",
        "run_python_snippet(code=\"import math\\nfor i in range(1, 6):\\n    print(i, math.factorial(i))\")",
        "run_python_snippet(code=\"print('index,prime,fib')\\n# ... full snippet ...\")",
        "run_python_snippet(code=<snippet>)"
      ],
      "inputs": [
        "`run_python_snippet(code: str)`",
        "`code`: a complete, self-contained Python snippet.",
        "The snippet must use print() to emit all output - the return value of the last",
        "Imports are restricted to a safe whitelist: math, itertools, collections, csv, io,",
        "os, sys, subprocess, open, eval, exec, and file I/O are blocked.",
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
        "execute_file_instruction(\"write the system information to ./data/<name>.csv\")",
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
      "skill_name": "PageAssess Skill",
      "relative_path": "code/skills/PageAssess/skill.md",
      "purpose": "Fetch a URL, classify whether it is an article page or an index/listing page, and return a",
      "module": "code/skills/PageAssess/page_assess_skill.py",
      "functions": [
        "assess_page(...)",
        "assess_page(url, topic, max_links)",
        "assess_page(url: str, topic: str = \"\", max_links: int = 10)"
      ],
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
      "skill_name": "WebMine Skill",
      "relative_path": "code/skills/WebMine/skill.md",
      "purpose": "STAGE 1 - MINING ONLY. Fetch URLs or run DuckDuckGo searches and save raw content as .md files in 01-Mine. Does not analyse, summarise, or produce reports. QUERY RULES: Use natural topic + source name (e.g. 'UK news March 2026 BBC', 'French news March 2026 Le Monde'). Use month name + year for recency - NOT ISO dates or day numbers ('UK news March 11 2026' and 'BBC News 2026-03-11' both return no results). NEVER use site: operators. When a prompt contains a date like 2026-03-11, convert it to 'March 2026' for the query string.",
      "module": "code/skills/WebMine/web_mine_skill.py",
      "functions": [
        "mine_search(\"electric vehicle battery 2026\", \"CarIndustry\", max_results=5)",
        "mine_search(query, domain, max_results, fetch_content, content_words)",
        "mine_search(query: str, domain: str, max_results: int = 5, fetch_content: bool = True, content_words: int = 600)",
        "mine_search_deep(\"UK politics March 2026\", \"GeneralNews\", target_articles=8)",
        "mine_search_deep(query, domain, max_results, max_articles_per_result, min_words, content_words, target_articles)",
        "mine_search_deep(query: str, domain: str, max_results: int = 10, max_articles_per_result: int = 2, min_words: int = 250, content_words: int = 1500, target_articles: int = 5)",
        "mine_url(\"https://example.com/article\", \"GeneralNews\")",
        "mine_url(url, domain, slug, max_words)",
        "mine_url(url: str, domain: str, slug: str = None, max_words: int = 1200)"
      ],
      "inputs": [
        "`mine_url(url, domain, slug, max_words)`",
        "`url`: full HTTP/HTTPS URL to fetch and save (required)",
        "`domain`: research domain label for filing, e.g. \"GeneralNews\" or \"CarIndustry\" (required)",
        "`slug`: optional item folder name; defaults to the page title if omitted",
        "`max_words`: maximum words of extracted body text, 50\u20134000, default 1200",
        "`mine_search(query, domain, max_results, fetch_content, content_words)`",
        "`query`: search query string (required)",
        "`domain`: research domain label (required)",
        "`max_results`: number of search results to record, 1\u201310, default 5",
        "`fetch_content`: if `True`, fetch each result URL and embed extracted prose inline;",
        "`content_words`: maximum prose words to embed per result when `fetch_content=True`, 50\u20134000, default 600",
        "`mine_search_deep(query, domain, max_results, max_articles_per_result, min_words, content_words, target_articles)`",
        "`query`: search query string (required)",
        "`domain`: research domain label (required)",
        "`max_results`: number of DDG results to process, 1\u201320, default 10",
        "`max_articles_per_result`: for each index/section result, how many child article links to",
        "`min_words`: minimum prose word count for a page to qualify as a mineable article, 100\u2013800, default 250",
        "`content_words`: maximum words to save per article file, 200\u20134000, default 1500",
        "`target_articles`: stop saving once this many articles have been collected, 1\u201320, default 5"
      ],
      "outputs": [
        "`mine_url` and `mine_search` return a confirmation string: `Saved: <absolute path to .md file>`",
        "`mine_search_deep` returns a multi-line summary: `Mined N article(s) for: '<query>'` followed",
        "On failure: a descriptive error string beginning with `Error:`",
        "When `mine_search` is called with `fetch_content=True` (the default), the saved `results.md` includes"
      ]
    },
    {
      "skill_name": "WebResearchAnalysis Skill",
      "relative_path": "code/skills/WebResearchAnalysis/skill.md",
      "purpose": "**STAGE 2 - Analysis only.**",
      "module": "code/skills/WebResearchAnalysis/web_research_analysis_skill.py",
      "functions": [
        "create_daily_summary(domain, date, topic, model, num_ctx)",
        "create_daily_summary(domain, date=\"\", topic=\"\", model=\"20b\", num_ctx=131072)",
        "list_analyses(domain, max_days)",
        "list_analyses(domain, max_days=7)",
        "list_mine_days(domain, max_days)",
        "list_mine_days(domain, max_days=7)"
      ],
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "WebResearchOutput Skill",
      "relative_path": "code/skills/WebResearchOutput/skill.md",
      "purpose": "Dispatches rendered HTML reports from the `03-Presentation` research stage to external destinations. This skill handles **delivery mechanics only** - HTML rendering and template styling are handled entirely by **WebResearchReport**.",
      "module": "code/skills/WebResearchOutput/web_research_output_skill.py",
      "functions": [
        "get_analysis_text(domain, date)",
        "list_analyses(domain, max_days)",
        "list_reports(domain, max_days=7)",
        "send_daily_summary(domain, date, list_name, subject)",
        "send_report_email(domain, date=\"\", list_name=\"default\", subject=\"\")"
      ],
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "WebResearchReport Skill",
      "relative_path": "code/skills/WebResearchReport/skill.md",
      "purpose": "Reads an analysis file produced by **WebResearchAnalysis** and renders it as a polished, self-contained HTML report saved to the `03-Presentation` research stage.",
      "module": "code/skills/WebResearchReport/web_research_report_skill.py",
      "functions": [
        "get_analysis_text(domain, date=\"\")",
        "get_report_html(domain, date=\"\")",
        "list_reports(domain, max_days=7)",
        "save_html_report(domain, date=\"\", template=\"default\")"
      ],
      "inputs": [],
      "outputs": []
    },
    {
      "skill_name": "WebSearch Skill",
      "relative_path": "code/skills/WebSearch/skill.md",
      "purpose": "Search the web using DuckDuckGo (no API key required) and return a ranked list of results with title, URL, and snippet. Pure Python - no external service accounts needed.",
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
