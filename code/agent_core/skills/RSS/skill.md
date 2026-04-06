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

## Canonical workflow

For any request to read, summarise, or report on news articles from MiniFeed, follow this pattern exactly:

1. **Search or browse** - call `rss_search(query, limit=20)` (do NOT pass `fetch_full=True` here) or `rss_get_recent(hours=N, limit=20)` to get a readable list of entries. Each entry includes `id`, `domain`, and `headline`. Do NOT use `research_traverse` or `search_web` for this step - MiniFeed is local and cannot be found on the web.
2. **Select** - pick the entries you want to read. Filter on `headline` to confirm AI-relevance. For "top stories" tasks, prefer entries from established news outlets (Ars Technica, BBC, Wired, TechCrunch, Tom's Hardware, The Verge) over personal blogs, GitHub repos, and App Store pages.
3. **Fetch body text** - for each selected entry call `rss_get_entry(domain=entry["domain"], entry_id=entry["id"])`. This returns the full `page_text` already scraped and stored by MiniFeed.
4. **Summarise** - produce the output from the `page_text` returned in step 3.

Search and recent results do not include a `url` field - this is intentional. There is nothing to pass to `fetch_page_text`. Use `rss_get_entry` only.

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
- `limit` *(optional, default 20, max 100)* - maximum number of results to return. The parameter name is `limit` - not `max_results`, `count`, or `num`.
- `fetch_full` *(optional, default false)* - when true, each result includes page_text (the full scraped article body already stored in MiniFeed - no web fetch needed). Do not use on the first search call. For multiple articles, search with fetch_full=False first to get headlines and IDs, then call rss_get_entry for each article you need to summarise. Using fetch_full=True with more than 2 results will produce a response too large to read inline.

Returns a list of dicts. Without `fetch_full`: `id`, `feed_name`, `headline`, `published`, `ingested_at`, `domain`. With `fetch_full`: adds `page_text`. The `url` field is intentionally omitted - use `rss_get_entry(domain, id)` to retrieve article body text.

### `rss_get_recent(hours=24, limit=20)`
- `hours` *(optional, default 24)* - look back window in hours (e.g. 6, 48). Searches all ingested domains.
- `limit` *(optional, default 20, max 100)* - maximum entries to return.

Returns entries ingested within the window, newest first. Fields: `id`, `feed_name`, `headline`, `published`, `ingested_at`, `domain`. The `url` field is intentionally omitted - use `rss_get_entry(domain, id)` to retrieve article body text.

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
  "published": "2026-04-05T07:30:00",
  "ingested_at": "2026-04-05T07:45:12",
  "domain": "tech"
}]
```
Note: `url` is not included in search or recent results. Pass `domain` and `id` to `rss_get_entry` to retrieve the article.

**`rss_get_entry`** - `dict` with `id`, `feed_name`, `headline`, `published`, `ingested_at`, `domain`, `metadata`, and `page_text`. Summarise from `page_text` directly. Do not call `fetch_page_text` on anything returned from this function.

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

**RULE 1 - Never call fetch_page_text or any web fetch tool on a URL that came from a MiniFeed result.**
MiniFeed already scraped and stored the article body. Live fetches are unnecessary, often return 403 or truncated sidebar HTML, and waste a round. Every entry returned by `rss_search` or `rss_get_recent` has `domain` and `id` fields. Pass those directly to `rss_get_entry(domain, entry_id)` to get the full stored body.

Correct pattern:
```
results = rss_search(query="AI", limit=20)      # get list with domain + id
entry   = rss_get_entry(domain=results[0]["domain"], entry_id=results[0]["id"])  # get page_text
# summarise from entry["page_text"] - no further tool calls needed
```

Wrong pattern (never do this):
```
results = rss_search(query="AI", limit=20)
entry   = rss_get_entry(domain=results[0]["domain"], entry_id=results[0]["id"])
fetch_page_text(...)    # WRONG - page_text is already in entry; there is nothing to fetch
```

**RULE 2 - For topic-specific requests, start with rss_search, not rss_get_recent.**
`rss_get_recent` returns whatever was ingested most recently across all feeds. For an AI news request, the most recent items are almost certainly not AI stories - they will be general news. Start with `rss_search(query="artificial intelligence", limit=50)` to get topic-matched results immediately.

**RULE 3 - Never use research_traverse or search_web to discover MiniFeed content.**
MiniFeed is a local server - it has no public URL and cannot be found by any web search engine. Calling `research_traverse` or `search_web` with a query mentioning "MiniFeed" will return nothing useful. All article discovery must use the RSS tools: `rss_search`, `rss_get_recent`, `rss_get_entries`, or `rss_get_entry`. Web tools are only valid if the user explicitly asks for information from the open web that is not in MiniFeed.

Wrong pattern (never do this):
```
research_traverse(query="AI industry stories from MiniFeed ...")  # WRONG - MiniFeed is local; web search cannot reach it
search_web(query="MiniFeed AI articles ...")                      # WRONG - same reason
```

**RULE 4 - Never use fetch_full=True on bulk searches.**
Using `fetch_full=True` with `limit > 2` produces a response too large to read inline, triggering scratchpad auto-save and hiding all results from the model in the same round. Always search with `fetch_full=False` (or omit it) to get a readable list of headlines and IDs, then call `rss_get_entry(domain, entry_id)` individually for each article you actually need to summarise.

Wrong pattern (never do this):
```
rss_search(query="AI", limit=20, fetch_full="true")     # WRONG - floods context; auto-saves to scratchpad
rss_get_recent(hours="120", limit=50)                   # already fine since fetch_full defaults False, but limit 50 still floods
```

Correct pattern:
```
results = rss_search(query="artificial intelligence", limit=20)   # fetch_full omitted - returns headlines + ids only
# inspect results in-context, pick the 5 most relevant by headline
for entry_id, domain in selected:
    entry = rss_get_entry(domain=domain, entry_id=entry_id)       # fetch body one at a time
    # summarise from entry["page_text"]
```

**Always check MiniFeed before reaching for web tools.**
MiniFeed is a local server - queries are instant and free. For any news, headlines, or recent articles request, call rss_search or rss_get_recent first. Only move to web tools if MiniFeed returns no useful results or the user explicitly asks for a broader search.

**If a tool result is truncated with a scratchpad key, load that key before drawing any conclusions.**
When a result is large it is auto-saved and the visible portion ends with `... [truncated - full content auto-saved to scratchpad key: _tc_r1_rss_search]` (or similar). The truncated portion may contain the most relevant results. Always call `scratch_load(key)` to read the full list before interpreting results or deciding no matches were found.

**`rss_search` and `rss_get_recent` always search all domains - there is no domain filter.**
Domain names are internal to MiniFeed and MiniAgentFramework has no way to know them in advance. Use `rss_list_domains` only when you need exact domain names to pass to `rss_get_entries` or `rss_get_entry`.

**Never use web fetch tools on URLs returned by MiniFeed results** (see RULE 1 above).
The article body text is already scraped and stored locally. Call `rss_get_entry(domain, entry_id)` using the `domain` and `id` fields from the result.

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

**For "top stories" tasks, apply editorial judgment when selecting articles.**
Prefer stories from established news outlets (Ars Technica, BBC, Wired, TechCrunch, Tom's Hardware, The Verge, ABC News) over personal blog posts, GitHub repository pages, and App Store listings. A GitHub README or a personal developer blog is not a "top AI story" even if it is the most recent search result. Pick articles that a news editor would consider newsworthy: product launches, research findings, industry events, policy changes.
