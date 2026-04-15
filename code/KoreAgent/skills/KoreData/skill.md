# KoreData Skill

## Purpose
Search and retrieve content from the local KoreData system via the KoreDataGateway. KoreData
aggregates four services behind a single search API:
- **KoreFeeds** - a repackaged RSS archive with full article text
- **KoreReference** - a local encyclopedia (Wikipedia clone)
- **KoreLibrary** - a local book repository
- **KoreRAG** - an FTS5-indexed store of internal user documents (company process docs, project
  data files, ad hoc notes)

Use this skill to search recent news, look up encyclopedia articles, find books, or retrieve
internal documents - all in one call. Follow up with the appropriate get function for full content.

## Trigger keyword: koredata

## Interface
- Module: `code/KoreAgent/skills/KoreData/koredata_skill.py`
- Functions:
  - `koredata_search(query, domains=None, since=None, until=None, limit=5)`
  - `koredata_get_article(title)`
  - `koredata_get_entry(domain, entry_id)`
  - `koredata_get_book(book_id)`
  - `koredata_get_chunk(chunk_id)`
  - `koredata_status()`

## Configuration
Set `"koredataurl"` in `default.json` (repo root) to the KoreDataGateway base URL, e.g.:
```json
{ "koredataurl": "http://localhost:8200" }
```
If absent, all functions return a descriptive error string.

## Canonical workflow

When the user's prompt names KoreData, asks to search KoreData, or asks to summarise a book,
article, or news item that could be held locally, follow this pattern exactly - do NOT call
search_web, research_traverse, or fetch_page_text instead:

1. **Search** - call `koredata_search(query, domains=[...], limit=5)`.  Omit `domains` to
   search all four services at once.  The response contains a `results` dict keyed by domain
   (`"feeds"`, `"reference"`, `"library"`, `"rag"`), each holding a list of summary dicts.
2. **Select** - pick relevant results from the appropriate domain lists.
   - For feeds: note `source` (domain slug) and `id` from each entry.
   - For reference: note the `title` from each article.
   - For library: note the `id` from each book.
   - For rag: note the `id` from each chunk.
3. **Retrieve full content** - this step is mandatory. You MUST call the matching get function
   for each selected result before writing your answer. Do NOT summarise from the search snippet
   alone - the snippet is too short to be a reliable source.
   - `koredata_get_article(title)` for reference articles
   - `koredata_get_entry(source, id)` for feed entries (pass `source` as the domain)
   - `koredata_get_book(id)` for library books
   - `koredata_get_chunk(id)` for RAG chunks
4. **Summarise** - produce the output from the full content returned in step 3, not from
   training knowledge. Never cite a KoreData ID as a source without having called the
   corresponding get function first.

Do NOT pass the `url` field from search results to WebFetch - these are gateway-relative paths,
not external URLs.  Always use the specific get functions above.

## Parameters

### `koredata_search(query, domains=None, since=None, until=None, limit=5)`
- `query` *(required)* - natural-language or keyword query string matched across all requested
  domains.
- `domains` *(optional)* - list of services to search: `"feeds"`, `"reference"`, `"library"`,
  `"rag"`. Omit or pass `None` to search all four.
- `since` *(optional)* - ISO 8601 date `YYYY-MM-DD` - earliest published-date filter, applied
  to KoreFeeds only.
- `until` *(optional)* - ISO 8601 date `YYYY-MM-DD` - latest published-date filter, applied to
  KoreFeeds only.
- `limit` *(optional, default 5, max 20)* - maximum results per domain.

Returns a dict:
```json
{
  "query": "...",
  "domains_searched": ["feeds", "reference", "library", "rag"],
  "results": {
    "feeds":     [ { "type": "feed_entry",        "id": 1042, "title": "...", "source": "bbc",
                     "published_at": "...", "snippet": "...", "url": "/feeds/bbc/1042" } ],
    "reference": [ { "type": "reference_article",  "title": "...", "summary": "...",
                     "snippet": "...", "word_count": 4200, "url": "/reference/Title" } ],
    "library":   [ { "type": "library_book",       "id": 7, "title": "...", "author": "...",
                     "snippet": "...", "url": "/library/7" } ],
    "rag":       [ { "type": "rag_chunk",          "id": 42, "title": "...", "source": "...",
                     "tags": "...", "snippet": "...", "url": "/rag/42" } ]
  }
}
```

### `koredata_get_article(title)`
- `title` *(required)* - article title exactly as it appears in a `koredata_search` reference
  result (e.g. `"Arctic_sea_ice_decline"`).

Returns the full article dict including `body`, `sections`, outbound `links`, and `backlinks`.

### `koredata_get_entry(domain, entry_id)`
- `domain` *(required)* - the `source` field from a feed search result (domain slug).
- `entry_id` *(required)* - the `id` field from a feed search result.

Returns the full feed entry dict including scraped `page_text`.

### `koredata_get_book(book_id)`
- `book_id` *(required)* - numeric book ID from a library search result.

Returns the full book dict including `body` (stored as Markdown).

### `koredata_get_chunk(chunk_id)`
- `chunk_id` *(required)* - numeric chunk ID from a RAG search result.

Returns the full chunk dict including decompressed `content`, `title`, `source`, and `tags`.

### `koredata_status()`
No parameters. Returns the gateway health dict with per-child `healthy` and stats fields.
Use this to diagnose connectivity before searching.

## Output shapes

**`koredata_search`** - returns the gateway response dict described above.

**`koredata_get_article`** - full reference article dict, e.g.:
```json
{
  "title": "Arctic sea ice decline",
  "summary": "...",
  "body": "...",
  "sections": [...],
  "links": [...],
  "backlinks": [...]
}
```

**`koredata_get_entry`** - full feed entry dict including `page_text`.

**`koredata_get_book`** - full library book dict including `body` (Markdown).

**`koredata_get_chunk`** - full RAG chunk dict, e.g.:
```json
{
  "id": 42,
  "title": "...",
  "source": "...",
  "tags": "...",
  "content": "..."
}
```

**`koredata_status`** - health dict:
```json
{
  "service": "KoreDataGateway",
  "children": {
    "korefeed":      { "healthy": true, ... },
    "korelibrary":   { "healthy": true, ... },
    "korereference": { "healthy": true, ... },
    "korerag":       { "healthy": true, ... }
  }
}
```

## Tool selection guidance

**KoreData is the default first choice for any factual, reference, news, or book query.**
Before calling search_web, research_traverse, or fetch_page_text on any informational question,
call `koredata_search` first. KoreData is local, instant, and requires no internet access. Only
move to web tools after KoreData returns empty results for all relevant domains.

**Topic routing:**
- News and recent events - `koredata_search(query, domains=["feeds"])`
- Encyclopedia, facts, history, biography, concepts - `koredata_search(query, domains=["reference"])`
- Books, literature, full texts - `koredata_search(query, domains=["library"])`
- Internal documents, company processes, project data, ad hoc notes - `koredata_search(query, domains=["rag"])`
- Unknown or cross-cutting - omit `domains` to search all four at once

**Fall back to web tools only when KoreData has nothing.**
If `koredata_search` returns empty results across all relevant domains, then use `search_web`
or `research_traverse`. Never skip the KoreData step unless the prompt explicitly says
"search the web", "search online", or "search the internet".

**Use `domains` to narrow scope.**
Pass a specific `domains` list when the content type is clear to reduce response size and
speed up retrieval. Omit `domains` only when the request genuinely spans multiple content types.

**Use `since`/`until` for date-bounded news searches.**
These filters apply to KoreFeeds only. Useful for "what happened last week" style queries -
pass `since="YYYY-MM-DD"`.

**Use the scratchpad for large full-content responses.**
Article bodies and book bodies can be several thousand words. Park them with `scratch_save`
before passing to downstream steps.

## Examples
- `koredata_search("arctic ice", domains=["feeds", "reference"], since="2025-01-01")` - recent
  news and encyclopedia results about arctic ice since January 2025
- `koredata_search("onboarding process", domains=["rag"])` - search internal documents for
  onboarding process docs
- `koredata_get_article("Arctic_sea_ice_decline")` - full encyclopedia article
- `koredata_get_entry("bbc", 1042)` - full BBC feed entry with scraped page text
- `koredata_get_book(7)` - full library book body
- `koredata_get_chunk(42)` - full RAG chunk with decompressed content
- `koredata_status()` - check whether all child services are online
