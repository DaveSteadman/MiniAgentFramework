# WebMine Skill

## Purpose
Mine web content (direct URLs or DuckDuckGo searches) and save raw results in `webresearch/01-Mine/<domain>/yyyy/mm/dd/`; for DDG use short natural-language queries with month/year recency like `"EU news headlines March 2026"` and never use ISO dates like `2026-03-14` in the search query.
Does not analyse, summarise, or produce reports.

**CRITICAL - DDG query rules:** Use `"topic month-name year source"` format (e.g. `"UK news March 2026 BBC"`). Never include ISO dates or day numbers in queries - `"UK news March 11 2026"` and `"BBC News 2026-03-11"` both return no results. Never use `site:` operators. A prompt date like `2026-03-11` is for folder filing only - convert it to `"March 2026"` in the query string.

**Planning shortcut:** If the user does not explicitly provide a date, do not append today's date. Keep the query topical and source-oriented, for example `"EU news headlines Reuters"` or `"EU news headlines March 2026 Reuters"` when recency needs to be explicit.

## Interface
- Module: `code/skills/WebMine/web_mine_skill.py`
- Primary functions:
  - `mine_url(url: str, domain: str, slug: str = None, max_words: int = 1200)`
  - `mine_search(query: str, domain: str, max_results: int = 5, fetch_content: bool = True, content_words: int = 600)`
  - `mine_search_deep(query: str, domain: str, max_results: int = 10, max_articles_per_result: int = 2, min_words: int = 250, content_words: int = 1500, target_articles: int = 5)`

## Input
- `mine_url(url, domain, slug, max_words)`
  - `url`: full HTTP/HTTPS URL to fetch and save (required)
  - `domain`: research domain label for filing, e.g. "GeneralNews" or "CarIndustry" (required)
  - `slug`: optional item folder name; defaults to the page title if omitted
  - `max_words`: maximum words of extracted body text, 50–4000, default 1200

- `mine_search(query, domain, max_results, fetch_content, content_words)`
  - `query`: search query string (required)
  - `domain`: research domain label (required)
  - `max_results`: number of search results to record, 1–10, default 5
  - `fetch_content`: if `True`, fetch each result URL and embed extracted prose inline;
    results yielding fewer than 250 words, or link-dense section/listing pages, are saved
    as index pages with article-candidate links instead of prose; **default `True`**
  - `content_words`: maximum prose words to embed per result when `fetch_content=True`, 50–4000, default 600

- `mine_search_deep(query, domain, max_results, max_articles_per_result, min_words, content_words, target_articles)`
  - `query`: search query string (required)
  - `domain`: research domain label (required)
  - `max_results`: number of DDG results to process, 1–20, default 10
  - `max_articles_per_result`: for each index/section result, how many child article links to
    follow and mine, 1–5, default 2
  - `min_words`: minimum prose word count for a page to qualify as a mineable article, 100–800, default 250
  - `content_words`: maximum words to save per article file, 200–4000, default 1500
  - `target_articles`: stop saving once this many articles have been collected, 1–20, default 5

## Output
- `mine_url` and `mine_search` return a confirmation string: `Saved: <absolute path to .md file>`
- `mine_search_deep` returns a multi-line summary: `Mined N article(s) for: '<query>'` followed
  by a `Folder: <path>` line for the parent query folder, then one `Saved: <path>` line per article.
- On failure: a descriptive error string beginning with `Error:`
- When `mine_search` is called with `fetch_content=True` (the default), the saved `results.md` includes
  extracted prose (up to `content_words` words) inline under each result that is an article;
  results classified as index/listing pages (< 250 words or link-dense) are saved with a list
  of article-candidate links discovered from the page.

## Saved file structure

`mine_url` saves a numbered `.md` file directly in the date directory:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>.md
```
File contents:
```markdown
# Page Title

**Source URL:** https://example.com/article
**Mined:** 2026-03-07 14:32
**Domain:** GeneralNews

---

## Content

[extracted prose text up to max_words words]
```

`mine_search` saves a numbered `.md` file directly in the date directory:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<query>.md
```
File contents:
```markdown
# Search: python 3.14 features

**Query:** python 3.14 features
**Searched:** 2026-03-07
**Domain:** GeneralNews
**Results returned:** 5

---

## Results

### [1] Title of first result
- **URL:** https://example.com
- **Snippet:** Short description text
```

`mine_search_deep` saves each article as its own numbered `.md` file directly in the date directory:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<article-title>.md
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<article-title>.md
...
```
All articles from one call land in the same flat `yyyy/mm/dd/` directory.

## Workspace layout (three stages)
```
webresearch/
  01-Mine/          <- raw fetched content (written by this skill)
  02-Analysis/      <- summarised / processed artefacts
  03-Presentation/  <- final polished outputs
```
Each stage uses `<domain>/yyyy/mm/dd/` - all files sit directly in the date directory.
Path management is handled by `code/webresearch_utils.py`.

## Query construction

DuckDuckGo is the search engine. Write queries that work well with it:

**DO:**
- Use natural topic + source name: `"UK news BBC"`, `"UK politics Guardian"`, `"French news Le Monde"`
- Use month + year for recency: `"UK news March 2026 BBC"` - human-readable month names index well
- Keep queries short: 3–5 words

**DO NOT:**
- Include ISO dates in queries: `"BBC News 2026-03-11"` - almost always returns no results
- Include day numbers in queries: `"UK news March 11 2026"` - also returns no results
- Use `site:` operators: `"site:bbc.co.uk"` - unreliable in DuckDuckGo's HTML interface
- Use `intitle:`, `inurl:`, or other advanced operators - not supported

When a prompt contains a date like `2026-03-11`, use that date only for the `domain` filing - convert it to `"March 2026"` for the search query string itself.

| Prompt context | Good query | Bad query |
|---|---|---|
| "UK news for 2026-03-11" | `"UK news March 2026 BBC"` | `"BBC News 2026-03-11"` |
| "French news today" | `"French news March 2026 Le Monde"` | `"2026-03-11 site:lemonde.fr"` |
| "German headlines" | `"German news March 2026 Der Spiegel"` | `"Der Spiegel 2026-03-11"` |

## Typical trigger phrases

**`mine_url`** - you have a specific URL to save:
- `mine this URL into the <domain> research area`
- `mine the URL <url> into <domain>`
- `fetch and save <url> to the <domain> research area`
- `save this article/page to the <domain> research area`

**`mine_search`** - search and save a results summary (fast, one file):
- `web mine <topic> into the <domain> domain`
- `web mine <topic> for <date> into the <domain> domain`
- `search for <query> and save to the <domain> research area`
- `search for <query> and save results to <domain>`

**`mine_search_deep`** - search and mine individual articles (slower, multiple files, maximum content):
- `deep mine <query> into <domain>`
- `deep mine <topic> and save articles to <domain>`
- `deep mine <query> in the <domain> area`

**Use this skill whenever the user asks to save, store, mine, or file web content into a named domain or research area.**
Do NOT use WebSearch or WebExtract for these requests - those skills return content to the LLM but do not save anything to the webresearch workspace.

**Choosing the right function:**
- `mine_url` - you have a specific article URL and want to save it.
- `mine_search` - **default for all "web mine" and "search X into Y" prompts.** Fast: one `.md` file with inline snippets per query.
- `mine_search_deep` - only when the user explicitly says **"deep web mine"**. Slower: fetches and saves each qualifying article as its own file.

## Examples
- `mine_url("https://example.com/article", "GeneralNews")`
  → `webresearch/01-Mine/GeneralNews/2026/03/07/001-article-title.md`

- `mine_search("electric vehicle battery 2026", "CarIndustry", max_results=5)`
  → `webresearch/01-Mine/CarIndustry/2026/03/07/001-electric-vehicle-battery-2026.md`

- `mine_search_deep("UK politics March 2026", "GeneralNews", target_articles=8)`
  → up to 8 `.md` files saved directly in `webresearch/01-Mine/GeneralNews/2026/03/08/`

## Date tokens in queries
Query strings and URLs passed to any function support date tokens that are resolved at
execution time. This keeps scheduled JSON entries current without manual edits:

| Token | Example output (if today is 2026-03-08) |
|-------|------------------------------------------|
| `{today}` | `2026-03-08` |
| `{month_year}` | `March 2026` |
| `{month}` | `March` |
| `{year}` | `2026` |
| `{week}` | `10` |

Tokens are case-insensitive. A scheduled entry like:
```json
{ "user-prompt": "dig into 'UK politics {month_year}' and save articles to GeneralNews." }
```
becomes `"UK politics March 2026"` in March and `"UK politics April 2026"` in April automatically.

## Notes
- Uses DuckDuckGo HTML search - no API key or account required.
- Uses `beautifulsoup4` for high-quality content extraction; falls back to stdlib `html.parser`.
- Extracted prose is deduplicated before saving - responsive-layout pages that repeat the same
  content block for different viewport sizes will not produce garbled repeated text.
- `mine_url` works best on article-level URLs. For homepages or section index pages, use the
  PageAssess skill first to classify the page and discover individual article links.
- `mine_search` with `fetch_content=True` adds latency proportional to `max_results` (one HTTP
  fetch per result). Keep `max_results` small (3–5) when using `fetch_content=True`.
- `mine_search_deep` stops collecting once `target_articles` articles are saved (default 5), even if
  more DDG results remain. Raise `target_articles` (e.g. `target_articles=10`) to collect more.
  It makes up to `max_results` result fetches, plus up to `max_results × max_articles_per_result`
  child fetches for index pages. Default settings make up to 10 + 20 = 30 requests maximum but
  stop as soon as 5 articles are saved. Set `max_results=5` for faster runs.
- The `webresearch/` tree is created automatically on first use.
- Stage 2 (Analysis) and Stage 3 (Presentation) share the same folder structure but are
  populated by separate processing skills (not yet implemented).
