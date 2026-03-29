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

## Tool selection guidance

**Check the scratchpad before searching.**
If relevant data from a prior step in this session is already stored, use `scratch_query` or
`scratch_load` rather than issuing a new search. Only search the web when the data is
confirmed absent from the scratchpad.

**Always call the search tool - never answer from training data.**
When the prompt says "search for", "search the web for", "find information about", or "look up",
a tool call is mandatory. The purpose of search prompts is to retrieve current, verified data -
not to recall training knowledge. If the tool returns no results, report that explicitly rather
than substituting an answer from memory.

**Choose between `search_web` and `search_web_text`:**
- Use `search_web_text` in almost all cases - returns formatted text ready for direct synthesis,
  no extra processing needed.
- Use `search_web` only when you need to iterate over individual result fields (URL, title,
  snippet) programmatically - for example when passing each URL to a subsequent `fetch_page_text`.

**The three-stage web chain - when to go beyond a search:**

`search_web` is Stage 1: it finds entry-point URLs. Know which stage you need next:

| What you have after search | Next step | When to use it |
|---|---|---|
| A specific article URL | `fetch_page_text(url, query=...)` | Reading a known article |
| A hub/listing/index URL | `get_page_links_text(url)` | Surveying what is on a front page before choosing items |
| Need multiple sources | `research_traverse(query)` | Full automated investigation |
| Stable reference topic | `lookup_wikipedia(topic)` | Faster than web search for known subjects |

The hub-page pattern - use `get_page_links_text` as an intermediate step when the search
result is a listing page (HN, GitHub trending, news homepage, forum index) rather than a
direct article. Get the links, park them, use `scratch_query` to select, then `fetch_page_text`
on the chosen items.

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
