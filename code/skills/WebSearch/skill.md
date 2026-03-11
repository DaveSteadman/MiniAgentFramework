# WebSearch Skill

## Purpose
Search the web using DuckDuckGo (no API key required) and return a ranked list of results with title, URL, and snippet. Pure Python - no external service accounts needed.

## Interface
- Module: `code/skills/WebSearch/web_search_skill.py`
- Primary functions:
  - `search_web(query: str, max_results: int = 5, timeout_seconds: int = 15)`
  - `search_web_text(query: str, max_results: int = 5, timeout_seconds: int = 15)`

## Input
- `search_web(query, max_results, timeout_seconds)`
  - `query`: search query string (required)
  - `max_results`: number of results to return, 1–10, default 5
  - `timeout_seconds`: network timeout, 5–30, default 15
- `search_web_text(query, max_results, timeout_seconds)`
  - Same arguments as `search_web`.

## Output
- `search_web(...)` returns a `list[dict]`, each entry containing:
  - `rank` (int): result position, starting at 1
  - `title` (str): page title
  - `url` (str): destination URL
  - `snippet` (str): short description from DuckDuckGo
  - On error: a single-entry list with `rank=0` and `snippet` describing the failure.
- `search_web_text(...)` returns a plain-text formatted string suitable for direct LLM consumption:
  ```
  Web search results for: <query>

  [1] Title of first result
      https://example.com/page
      Snippet describing the result.

  [2] ...
  ```

## Typical trigger phrases
- `search the web for ...`
- `find information about ...`
- `look up ...`
- `what is the latest news on ...`
- `search for ...`

## Example
- `search_web_text("Python 3.14 release notes", max_results=3)`
  Returns a formatted block of the top 3 DuckDuckGo results for that query.

## Notes
- Uses DuckDuckGo HTML search endpoint - no API key or account required.
- Uses stdlib `urllib` only - no `requests` dependency.
- Results reflect DuckDuckGo's current index; quality may vary by query.
- Pair with the WebExtract skill to fetch and read full page content from any result URL.
- **If the user wants to SAVE or STORE results into a research area or domain, use the WebResearch skill instead (`mine_search`). This skill only returns results to the LLM - it does not persist anything.**
