# WebFetch Skill

## Trigger keyword: fetch

## Purpose
Fetch a web page by URL and extract its readable prose content, stripping all HTML markup, navigation, scripts, advertisements, and other non-content noise. Returns clean text ready for LLM synthesis or summarization.

## Interface
- Module: `code/skills/WebFetch/web_fetch_skill.py`
- Entry point: `fetch_page_text(url: str, max_words: int = 1000, timeout_seconds: int = 15, query: str | None = None)`

## Parameters

### url
- Type: `str`
- Required: yes
- The full HTTP or HTTPS URL to fetch. Local paths and ftp are rejected.

### max_words
- Type: `int`
- Required: no
- Default: `1000`
- Range: `50` to `4000`
- Maximum number of words of body prose to return. Content is truncated at this limit.

### timeout_seconds
- Type: `int`
- Required: no
- Default: `15`
- Range: `5` to `60`
- Network timeout in seconds.

### query
- Type: `str | None`
- Required: no
- Default: `None`
- When provided, the full page is fetched and passed through an isolated LLM call that extracts
  only the facts relevant to the query. The returned answer is compact - typically a short list
  or paragraph - and does not flood the caller's context window with raw page content.
  Use this when you already know what you are looking for on the page.
  When `None`, the raw truncated page text is returned as usual.

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

## Scratchpad integration
Page text can be large. Use `scratch_save` to store it under a key and reference it with `{scratch:key}` in follow-up steps rather than repeating the full text inline.

Example chain:
1. `search_web("python asyncio tutorial")` - returns list of results with URLs
2. `fetch_page_text("https://example.com/asyncio-guide", max_words=2000)` - returns body prose
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
