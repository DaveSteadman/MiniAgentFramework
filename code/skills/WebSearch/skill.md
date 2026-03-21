# WebSearch Skill

## Purpose
Search the web using DuckDuckGo and return ranked results with title, URL, and snippet. No API key required. Use `search_web_text` when results will be read directly by the LLM; use `search_web` when the caller needs structured data. This skill only returns results - it does not persist or save anything.

## Trigger keyword: search

## Interface
- Module: `code/skills/WebSearch/web_search_skill.py`
- Functions:
  - `search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)`
  - `search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)`

## Parameters

### `search_web(query, max_results = 5, timeout_seconds = 15)`
- `query` *(required)* - search query string.
- `max_results` *(optional, default 5)* - number of results to return, 1-10.
- `timeout_seconds` *(optional, default 15)* - network timeout in seconds, 5-30.

### `search_web_text(query, max_results = 5, timeout_seconds = 15)`
- `query` *(required)* - search query string.
- `max_results` *(optional, default 5)* - number of results to return, 1-10.
- `timeout_seconds` *(optional, default 15)* - network timeout in seconds, 5-30.

## Output
- `search_web(...)` - returns `list[dict]`, each entry with `rank` (int), `title` (str), `url` (str), `snippet` (str). On error: single-entry list with `rank=0` and `snippet` describing the failure.
- `search_web_text(...)` - returns a plain-text formatted block with rank, title, URL, and snippet per result. Ready for direct LLM consumption.

## Triggers
Invoke this skill when the prompt contains any of these concepts or phrases:
- `search the web for`, `find information about`, `look up`
- `what is the latest news on`, `search for`, `find recent`

## Examples
- `search_web_text("Python 3.14 release notes", max_results=3)` - top 3 DuckDuckGo results as formatted text
  - Returns: `"Web search results for: Python 3.14 release notes\n\n[1] ..."`
- `search_web("Eiffel Tower height")` - structured result list for programmatic use
