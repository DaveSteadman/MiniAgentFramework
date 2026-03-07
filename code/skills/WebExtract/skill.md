# WebExtract Skill

## Purpose
Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.

## Interface
- Module: `code/skills/WebExtract/web_extract_skill.py`
- Primary functions:
  - `fetch_page_text(url: str, max_words: int = 400, timeout_seconds: int = 15)`

## Input
- `fetch_page_text(url, max_words, timeout_seconds)`
  - `url`: full HTTP/HTTPS URL to fetch (required)
  - `max_words`: maximum words of body text to return, 50–800, default 400
  - `timeout_seconds`: network timeout, 5–60, default 15

## Output
- `fetch_page_text(...)` returns a plain string containing:
  - The readable prose text extracted from the page body, up to `max_words` words.
  - `...[truncated]` appended if the content was cut.
  - A descriptive error string starting with `"Error:"` if the fetch or extraction failed.

## Typical trigger phrases
- `fetch the page at ...`
- `read the content of ...`
- `extract text from ...`
- `get the article from ...`
- `summarize the page at ...`

## Example
Typical chained usage — planner selects both WebSearch and WebExtract:
1. WebSearch returns a list of results including URLs.
2. `fetch_page_text("https://example.com/article", max_words=400)` → returns page prose.
3. Final LLM synthesizes an answer from the extracted text.

## Notes
- Uses `beautifulsoup4` (installed) for high-quality extraction; falls back to stdlib html.parser if unavailable.
- Only supports `http` and `https` URLs — local paths and ftp are rejected.
- Returns an error string (never raises) so orchestration can continue if a page fails to load.
- Best paired with the WebSearch skill which provides the candidate URLs.
- **If the user wants to SAVE or MINE a URL into a research area or domain, use the WebResearch skill instead (`mine_url`). This skill only returns text to the LLM — it does not persist anything.**
