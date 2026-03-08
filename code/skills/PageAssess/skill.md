# PageAssess Skill

## Purpose
Fetch a URL, classify whether it is an article page or an index/listing page, and return a
structured assessment including a prose preview and a filtered list of article-candidate links.

Use this skill when you need to decide how to handle an unknown URL before mining it — especially
when a URL might be a homepage, section index, or landing page rather than an individual article.
Also use it to discover article links from any page filtered by a topic.

## Interface
- Module: `code/skills/PageAssess/page_assess_skill.py`
- Primary functions:
  - `assess_page(url: str, topic: str = "", max_links: int = 10)`

## Input
- `assess_page(url, topic, max_links)`
  - `url`: full HTTP/HTTPS URL to assess (required)
  - `topic`: optional topic string to filter and rank returned links by word-overlap relevance
    (e.g. `"UK foreign policy"`, `"electric vehicles"`) — no LLM involved
  - `max_links`: maximum article-candidate links to return, 1–20, default 10

## Output
`assess_page(...)` returns a structured dict:
```json
{
  "url":           "https://final-url-after-redirects.com/page",
  "title":         "Page Title",
  "page_type":     "article",
  "word_count":    843,
  "link_count":    5,
  "prose_preview": "First 100 words of extracted prose ...",
  "article_links": [
    { "title": "Headline or anchor text", "url": "https://example.com/article" }
  ]
}
```

- `page_type` is one of:
  - `"article"` — substantial prose content (≥ 300 words, ≤ 4 links per 100 words)
  - `"index"` — listing/aggregation page (< 150 words, or ≥ 7 links per 100 words)
  - `"mixed"` — some content plus significant navigation (common on news section pages)
- `word_count`: prose words extracted after noise removal and deduplication
- `article_links`: sorted by `topic` match score when `topic` provided; otherwise page order
- On failure: `{"error": "description of what went wrong"}` — never raises

## Classification heuristics (deterministic — no LLM)

| Condition | Classification |
|---|---|
| `word_count < 150` | `"index"` |
| `word_count ≥ 300` AND `links-per-100-words ≤ 4.0` | `"article"` |
| `links-per-100-words ≥ 7.0` | `"index"` |
| Everything between those bounds | `"mixed"` |

## Typical trigger phrases
- `assess the page at <url>`
- `assess <url> for topic <topic>`
- `is <url> an article or a listing page`
- `what kind of page is <url>`
- `find article links on <url> about <topic>`
- `get links from <url> related to <topic>`
- `check whether <url> has article content`

## Planner decision guide

| `page_type` | Recommended next action |
|---|---|
| `"article"` | Call `mine_url` (WebResearch) directly — the page has substantial content worth saving |
| `"index"` | Do NOT mine the page itself; use `article_links` to get individual article URLs, then call `mine_url` on those |
| `"mixed"` | Try `mine_url`; if `word_count < 200` also use `article_links` to follow linked articles |

## Examples

```
assess_page("https://www.bbc.co.uk/news/uk", topic="foreign policy", max_links=5)
```
Returns `page_type="index"`, low `word_count`, and up to 5 article links whose headlines
match tokens from "foreign policy".

```
assess_page("https://www.bbc.co.uk/news/articles/abc123")
```
Returns `page_type="article"`, high `word_count`, short `article_links` list.

## Notes
- Links are extracted from the main content area only — `<nav>`, `<header>`, `<footer>`, `<aside>`
  and known noise containers are pruned before link extraction.
- Topic filtering is pure token overlap — short or very common words may over-match.
- This skill does NOT write any files to disk.
- To persist content, pass URLs from `article_links` to `mine_url` (WebResearch skill).
- Uses `beautifulsoup4` for high-quality extraction; falls back to stdlib `html.parser` if unavailable.
