# RSS Skill

## Purpose
Search and retrieve news articles that have been ingested by a local MiniFeed server. MiniFeed is a separate background service that monitors RSS feeds, fetches article body text, and stores everything in a full-text searchable database. This skill is a clean REST consumer - it never parses RSS directly. Use it to find recent news, browse articles by topic domain, or retrieve full article body text.

## Trigger keyword: rss

## Interface
- Module: `code/agent_core/skills/RSS/rss_skill.py`
- Functions:
  - `rss_list_domains()`
  - `rss_list_feeds()`
  - `rss_search(query, limit=20, fetch_full=False)`
  - `rss_get_recent(hours=24, limit=20)`
  - `rss_get_entries(domain, limit=20, offset=0)`
  - `rss_get_entry(domain, entry_id)`

## Configuration
Set `"minifeedurl"` in `default.json` (repo root) to the MiniFeed server base URL, e.g.:
```json
{ "minifeedurl": "http://localhost:8100" }
```
If absent, all functions return a descriptive error string.

## Parameters

### `rss_list_domains()`
No parameters. Returns a list of all domains MiniFeed has ingested, each with a `domain` name and `entry_count`. Use this to see what domains exist before using `rss_get_entries` or `rss_get_entry`, which require an exact domain name.

### `rss_list_feeds()`
No parameters. Returns all configured feeds, including those whose domain has no entries yet (e.g. feeds that were just added and have not been ingested). Each feed has `id`, `domain`, `name`, `url`, and `update_rate` (minutes). Use this when the user asks what topics are being tracked.

### `rss_search(query, limit=20, fetch_full=False)`
- `query` *(required)* - search terms matched against entry headlines and article body text. Searches all ingested domains. Multiple terms can be space- or comma-separated (e.g. c-130 pilot or c-130, pilot) - all terms must appear in the article (AND logic). Phrase order does not matter.
- `limit` *(optional, default 20, max 100)* - maximum number of results to return.
- `fetch_full` *(optional, default false)* - when true, each result includes page_text (the full scraped article body already stored in MiniFeed - no web fetch needed). Do not use on the first search call. For multiple articles, search with fetch_full=False first to get headlines and IDs, then call rss_get_entry for each article you need to summarise. Using fetch_full=True with more than 2 results will produce a response too large to read inline.

Returns a list of dicts. Without `fetch_full`: `id`, `feed_name`, `headline`, `url`, `published`, `ingested_at`, `domain`. With `fetch_full`: adds `page_text`.

### `rss_get_recent(hours=24, limit=20)`
- `hours` *(optional, default 24)* - look back window in hours (e.g. 6, 48). Searches all ingested domains.
- `limit` *(optional, default 20, max 100)* - maximum entries to return.

Returns entries ingested within the window, newest first. Fields: `id`, `feed_name`, `headline`, `url`, `published`, `ingested_at`, `domain`. Use this for what happened in the last N hours queries.

### `rss_get_entries(domain, limit=20, offset=0)`
- `domain` *(required)* - domain name to browse (from `rss_list_domains`).
- `limit` *(optional, default 20, max 100)* - entries per page.
- `offset` *(optional, default 0)* - skip this many entries for pagination.

Returns a list of full entry dicts including `page_text`. Ordered newest-first.

### `rss_get_entry(domain, entry_id)`
- `domain` *(required)* - domain the entry belongs to.
- `entry_id` *(required)* - numeric entry ID (from a search or browse result).

Returns the full entry dict including `page_text` (body text of the article as scraped by MiniFeed). Returns an error string if the entry does not exist.

## Output shapes

**`rss_list_domains`** - `list[dict]`
```json
[{ "domain": "tech", "entry_count": 412 }]
```

**`rss_search` / `rss_get_entries`** - `list[dict]`
```json
[{
  "id": 88,
  "feed_name": "Ars Technica",
  "headline": "EU fines Meta record amount over data transfers",
  "url": "https://arstechnica.com/...",
  "published": "2026-04-05T07:30:00",
  "ingested_at": "2026-04-05T07:45:12",
  "domain": "tech"
}]
```

**`rss_get_entry`** - `dict` with all fields above plus `page_text` and `metadata`.

On any error: a plain `str` describing the problem. Never raises.

## Triggers
Invoke this skill when the prompt contains concepts such as:
- `latest news`, `recent articles`, `news briefing`, `news summary`
- `what is happening in`, `headlines for`, `top stories`
- `search news for`, `find articles about`
- `what happened in the last`, `last N hours`, `past 24 hours`
- `what feeds are tracked`, `what topics are monitored`
- `rss`, `feeds`, `news feed`

## Tool selection guidance

**Always check MiniFeed before reaching for web tools.**
MiniFeed is a local server - queries are instant and free. For any news, headlines, or recent articles request, call rss_search or rss_get_recent first. Only move to web tools if MiniFeed returns no useful results or the user explicitly asks for a broader search.

**If a tool result is truncated with a scratchpad key, load that key before drawing any conclusions.**
When a result is large it is auto-saved and the visible portion ends with `... [truncated - full content auto-saved to scratchpad key: _tc_r1_rss_search]` (or similar). The truncated portion may contain the most relevant results. Always call `scratch_load(key)` to read the full list before interpreting results or deciding no matches were found.

**`rss_search` and `rss_get_recent` always search all domains - there is no domain filter.**
Domain names are internal to MiniFeed and MiniAgentFramework has no way to know them in advance. Use `rss_list_domains` only when you need exact domain names to pass to `rss_get_entries` or `rss_get_entry`.

**Use `fetch_full=True` only for single-article fetches - never on bulk searches.**
When summarising multiple articles, search with fetch_full=False to get headlines and entry IDs, then call `rss_get_entry(domain, entry_id)` for each article individually. Using fetch_full=True with limit > 2 makes the response too large to read inline and triggers scratchpad auto-save, hiding results from the model.

**Never use web fetch tools on URLs returned by MiniFeed results.**
The article body text is already scraped and stored locally. Fetching the live URL wastes a round, may return 403, and duplicates data MiniFeed already has. To get body text: either re-run `rss_search` with `fetch_full=True`, or call `rss_get_entry(domain, entry_id)` using the `domain` and `id` fields from the result. The `domain` and `id` fields in each result are exactly what `rss_get_entry` needs.

**If `rss_search` returns results, those results matched - the hit may be in body text, not in the headline.**
MiniFeed full-text search scans both headlines and scraped article body text. A result with an unrelated-looking headline still matched the query somewhere in its body. Never dismiss returned results because the headline does not obviously match. If the match location is unclear, re-run with `fetch_full=True` to see the body text and find the relevant passage. Never claim to have checked body text unless you called `rss_get_entry` or used `fetch_full=True`.

**Prefer `rss_search` over `rss_get_entries` when the user has a topic.**
Full-text search scans both headlines and body text across all domains. It is the fastest path to relevant articles without needing to know the domain in advance.

**Use `rss_get_entries` to browse a domain chronologically.**
Useful when the user says "what is the latest news on tech" without a specific query - fetch the newest entries from that domain and summarise the headlines.

**Use `rss_get_entry` when you need the article body.**
Search and browse results do not include `page_text`. If the user wants a summary or details of a specific article, call `rss_get_entry` with its `id` and `domain` to get the full body text ingested by MiniFeed.

**Do not fall through to WebSearch when MiniFeed has relevant data.**
If `rss_search` returns results the user's question is already answered from local data. Only escalate to `search_web` when MiniFeed returns no results or when the user explicitly asks for a broader web search.

**Prefer search_web over research_traverse for news queries.**
research_traverse is a deep multi-hop web crawler suited for obscure factual investigations where a simple search fails. It is slow and costly in rounds. For today's headlines or recent news, search_web is sufficient - use it first and only escalate to research_traverse when search_web returns nothing useful after at least one focused attempt.

**Check the domain field in search results.**
`rss_search` spans all domains by default. The `domain` field in each result tells you which feed category it came from, which you need to pass to `rss_get_entry`.
