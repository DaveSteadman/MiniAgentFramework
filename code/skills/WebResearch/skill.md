# WebResearch Skill

## Purpose
Mine web content into a structured three-stage research workspace. Handles both direct URL
fetching and DuckDuckGo searches, formatting results as clean Markdown files filed under
`webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/`.

## Interface
- Module: `code/skills/WebResearch/web_research_skill.py`
- Primary functions:
  - `mine_url(url: str, domain: str, slug: str = None, max_words: int = 600)`
  - `mine_search(query: str, domain: str, max_results: int = 5)`

## Input
- `mine_url(url, domain, slug, max_words)`
  - `url`: full HTTP/HTTPS URL to fetch and save (required)
  - `domain`: research domain label for filing, e.g. "GeneralNews" or "CarIndustry" (required)
  - `slug`: optional item folder name; defaults to the page title if omitted
  - `max_words`: maximum words of extracted body text, 50–1200, default 600

- `mine_search(query, domain, max_results)`
  - `query`: search query string (required)
  - `domain`: research domain label (required)
  - `max_results`: number of search results to record, 1–10, default 5

## Output
- Both functions return a confirmation string: `Saved: <absolute path to .md file>`
- On failure: a descriptive error string beginning with `Error:`

## Saved file structure

`mine_url` saves `source.md` inside a new numbered item folder:
```
webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/source.md
```
File contents:
```markdown
# Page Title

**Source URL:** https://example.com/article
**Mined:** 2026-03-07
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
- `mine this URL into the <domain> research area`
- `mine this URL into the <domain> area`
- `mine the URL <url> and save it to the <domain> research area`
- `mine the URL <url> into the <domain> area`
- `fetch and save <url> to the <domain> research area`
- `save this article to the <domain> research area`
- `save this page to the <domain> research area`
- `search the web for <query> and save results to <domain>`
- `search for <query> and save to the <domain> research area`
- `search for <query> and mine the results into <domain>`
- `mine the web for information about <topic> in the <domain> domain`
- `research <topic> and save it to <domain>`
- `search for <topic> and store it in the <domain> research area`

**Use this skill whenever the user asks to save, store, mine, or file web content into a named domain or research area.**
Do NOT use WebSearch or WebExtract for these requests — those skills return content to the LLM but do not save anything to the webresearch workspace.

## Examples
- `mine_url("https://example.com/article", "GeneralNews")`
  → `webresearch/01-Mine/GeneralNews/2026/03/07/001-article-title/source.md`

- `mine_search("electric vehicle battery 2026", "CarIndustry", max_results=5)`
  → `webresearch/01-Mine/CarIndustry/2026/03/07/001-search-electric-vehicle-battery-2026/results.md`

## Notes
- Uses DuckDuckGo HTML search — no API key or account required.
- Uses `beautifulsoup4` for high-quality content extraction; falls back to stdlib `html.parser`.
- The `webresearch/` tree is created automatically on first use.
- Stage 2 (Analysis) and Stage 3 (Presentation) share the same folder structure but are
  populated by separate processing skills (not yet implemented).
