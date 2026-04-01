# WebFetch Skill

## Purpose
Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.

## Trigger keyword: fetch

## Interface
- Module: `code/agent_core/skills/WebFetch/web_fetch_skill.py`
- Entry point: `fetch_page_text(url: str, max_words: int = 1000, timeout_seconds: int = 15, query: str | None = None)`

## Parameters

### `fetch_page_text(url, max_words, timeout_seconds, query)`
- `url` *(required)* - full HTTP or HTTPS URL to fetch. Local paths and ftp:// are rejected.
- `max_words` *(optional, default 1000)* - maximum words of body prose to return (range 50-4000).
- `timeout_seconds` *(optional, default 15)* - network timeout in seconds (range 5-60).
- `query` *(optional)* - when provided, runs an isolated LLM extraction pass and returns only the facts relevant to the query. Use when you know exactly what you are looking for on the page.

## Output
Returns a plain `str` containing:
- When `query` is None: the readable body text extracted from the page, up to `max_words` words.
- When `query` is set: a concise LLM-extracted answer targeted at the query, or `"Not found on this page."`
- A string beginning with `"Error:"` if the fetch or parse failed. Never raises.

## Triggers
- fetch the page
- read the content of
- get the article from
- open the URL
- read this URL
- what does the page say

## Tool selection guidance

**Check the scratchpad before fetching.**
If active scratchpad keys are listed in the system prompt, check whether the page content
already exists there before making a network request. Use `scratch_query(key, question)` to
extract a specific answer from stored content without re-fetching.

**This is Stage 3 in the web chain - use it on specific article/detail URLs.**

`fetch_page_text` is designed to read a single known page. If the URL you have is a hub or
listing page (front page, topic index, search results), use `get_page_links_text` first to
survey the available links, then call `fetch_page_text` on the selected items.

| Situation | Correct tool |
|---|---|
| URL is a specific article/repo/doc | `fetch_page_text(url, query=...)` |
| URL is a listing/hub/front page | `get_page_links_text(url)` first, then `fetch_page_text` |
| No URL yet, need to find one | `search_web_text(query)` first |

**Always use `query=` unless storing raw content for later processing.**

Raw mode (no `query`) injects up to 4,000 words directly into the main context window.  That
content must then be processed by the model in the very next round, compounding token cost.
Query mode runs an isolated throwaway LLM call and returns only a compact extracted answer -
the raw page text never enters the main context at all.

Use raw mode only when the explicit intent is to park the full page content into the scratchpad
via an immediate `scratch_save`, so it can be queried later with `scratch_query`.

Rule of thumb:
- Fetching a page to answer a question -> always use `query=`
- Fetching a page to store for later inspection -> use raw mode, then `scratch_save` immediately

## Scratchpad integration
Page text can be large. Use `scratch_save` to store it under a key and reference it with `{scratch:key}` in follow-up steps rather than repeating the full text inline.

Example chain:
1. `search_web("python asyncio tutorial")` - returns list of results with URLs
2. `fetch_page_text("https://example.com/asyncio-guide", query="summarise the key asyncio concepts")` - returns extracted answer
3. `scratch_save("asyncio_article", {result from step 2})` - stores text
4. LLM synthesizes answer from `{scratch:asyncio_article}`

## Examples

Minimal - fetch a known URL:
```
fetch_page_text("https://example.com/article")
```

With word limit:
```
fetch_page_text("https://example.com/article", max_words=500)
```

With targeted extraction - returns only relevant facts, keeps main context compact:
```
fetch_page_text("https://en.wikipedia.org/wiki/Monaco_Grand_Prix", query="Which years did Ferrari win and who was the driver?")
```

Notes:
- Uses `beautifulsoup4` for high-quality extraction; falls back to stdlib html.parser if unavailable.
- Only `http` and `https` schemes are supported.
- Returns an error string on failure so orchestration can continue gracefully.
- Naturally follows `search_web` or `search_web_text` which supply the candidate URLs.
