# KoreMine Skill

- Module: `code/skills/KoreMine/kore_mine_skill.py`

## Trigger keyword: KoreMine

When the user includes **KoreMine** in their message, use this skill. Do not use any other web-fetching, file-writing, or search tool for research mining tasks.

## Purpose
Mine web content (direct URLs or DuckDuckGo searches) and save raw results in `webresearch/01-Mine/<domain>/yyyy/mm/dd/`. Does not analyse, summarise, or produce reports.

## Functions

- `mine_url(url, domain, slug=None, max_words=1200)` - fetch a single URL and save it
- `mine_search(query, domain, max_results=5, fetch_content=True, content_words=600)` - DDG search and save results; **default for KoreMine tasks**
- `mine_search_deep(query, domain, max_results=10, max_articles_per_result=2, min_words=250, content_words=1500, target_articles=5)` - DDG search, follow links, save individual articles; only use when the user says **"deep"**

## DDG query rules

Use `"topic month-name year source"` format - e.g. `"UK news March 2026 BBC"`.
- Never include ISO dates or day numbers in queries - they return no results
- Never use `site:` or `intitle:` operators
- A prompt date like `2026-03-15` is for folder filing only - convert it to `"March 2026"` in the query

## Output

Saved path: `webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>.md`

Return value: `"Saved: <path>"` on success, `"Error: ..."` on failure.

## Pipeline position

```
KoreMine  ->  KoreAnalysis  ->  KoreReport
```

  → `webresearch/01-Mine/CarIndustry/2026/03/07/001-electric-vehicle-battery-2026.md`

- `mine_search_deep("UK politics March 2026", "GeneralNews", target_articles=8)`
  → up to 8 `.md` files saved directly in `webresearch/01-Mine/GeneralNews/2026/03/08/`

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
