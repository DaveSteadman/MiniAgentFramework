# WebResearch Skill

## Purpose
Mine web content into a structured three-stage research workspace. Handles both direct URL
fetching and DuckDuckGo searches, formatting results as clean Markdown files filed under
`webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/`.

## Interface
- Module: `code/skills/WebResearch/web_research_skill.py`
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

`mine_url` saves `source.md` inside a new numbered item folder:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/source.md
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

`mine_search` saves `results.md` inside a new numbered item folder:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-search-<query>/results.md
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

`mine_search_deep` groups all articles from one call under a single query-level folder:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-deep-<query>/
  001-<article-title>/source.md
  002-<article-title>/source.md
  ...
```
One top-level numbered folder per call; each article gets its own numbered sub-folder inside it.

## Workspace layout (three stages)
```
webresearch/
  01-Mine/          <- raw fetched content (written by this skill)
  02-Analysis/      <- summarised / processed artefacts
  03-Presentation/  <- final polished outputs
```
Each stage follows the same `<domain>/yyyy/mm/dd/NNN-<slug>/` structure.
Path management is handled by `code/webresearch_utils.py`.

## Typical trigger phrases

**`mine_url`** — you have a specific URL to save:
- `mine this URL into the <domain> research area`
- `mine the URL <url> into <domain>`
- `fetch and save <url> to the <domain> research area`
- `save this article/page to the <domain> research area`

**`mine_search`** — search and save a results summary (fast, one file):
- `search for <query> and save to the <domain> research area`
- `search for <query> and save results to <domain>`
- `research <query> into <domain>`
- `research <topic> and save it to <domain>`

**`mine_search_deep`** — search and mine individual articles (slower, multiple files, maximum content):
- `deep research <query> into <domain>`
- `deep research <topic> and save articles to <domain>`
- `deep research <query> in the <domain> area`

**Use this skill whenever the user asks to save, store, mine, or file web content into a named domain or research area.**
Do NOT use WebSearch or WebExtract for these requests — those skills return content to the LLM but do not save anything to the webresearch workspace.

**Choosing the right function:**
- `mine_url` — you have a specific article URL and want to save it.
- `mine_search` — fast search save: one `results.md` with inline snippets. Use when the user says **"research X into Y"**.
- `mine_search_deep` — maximum content: each qualifying article saved as its own file. Use when the user says **"deep research X into Y"**.

## Examples
- `mine_url("https://example.com/article", "GeneralNews")`
  → `webresearch/01-Mine/GeneralNews/2026/03/07/001-article-title/source.md`

- `mine_search("electric vehicle battery 2026", "CarIndustry", max_results=5)`
  → `webresearch/01-Mine/CarIndustry/2026/03/07/001-search-electric-vehicle-battery-2026/results.md`

- `mine_search_deep("UK politics March 2026", "GeneralNews", target_articles=8)`
  → `webresearch/01-Mine/GeneralNews/2026/03/08/NNN-deep-uk-politics-march-2026/`
  → up to 8 `source.md` files inside that folder, one per article discovered

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
- Uses DuckDuckGo HTML search — no API key or account required.
- Uses `beautifulsoup4` for high-quality content extraction; falls back to stdlib `html.parser`.
- Extracted prose is deduplicated before saving — responsive-layout pages that repeat the same
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
