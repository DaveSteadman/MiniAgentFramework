# WebSearch Skill

## Purpose
Search the web using DuckDuckGo and return ranked results with title, URL, and snippet. No API key required. Use `search_web_text` for direct synthesis - results come back as formatted text ready to read inline. Use `search_web` when you need to iterate over individual result fields (url, title, snippet) programmatically or pass them selectively to another skill. This skill only returns results - it does not persist or save anything.

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

## Scratchpad integration
Search results can be large.  When the result will be referenced in a later step (summarise,
extract a field, write to file), park it immediately with `scratch_save` so the full text does
not have to be re-fetched or carried as an inline string through subsequent planning rounds.

- `search_web_text("Python 3.14 release notes")` → `scratch_save("searchresult", <output>)` → use `{scratch:searchresult}` in downstream steps
- `write_file("data/results.txt", "{scratch:searchresult}")` - write parked search result without an extra `scratch_load` call

## Examples
- `search_web_text("Python 3.14 release notes", max_results=3)` - top 3 DuckDuckGo results as formatted text
  - Returns: `"Web search results for: Python 3.14 release notes\n\n[1] ..."`
- `search_web("Eiffel Tower height")` - structured result list for programmatic use
