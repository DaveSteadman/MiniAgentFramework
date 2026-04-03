# Kiwix Skill

## Purpose
Search and retrieve articles from a local Kiwix server. Kiwix hosts offline snapshots of Wikipedia, Project Gutenberg, and other reference libraries. Use this skill for factual lookups, article content, and reference research when a Kiwix server is available on the local network. Because Kiwix is local there is no rate-limiting, no bot detection, and no internet dependency.

## Trigger keyword: kiwix

## Interface
- Module: `code/agent_core/skills/Kiwix/kiwix_skill.py`
- Functions:
  - `kiwix_search(query, max_results=5, timeout=15)`
  - `kiwix_get_article(article_path, max_words=600, timeout=15)`

## Configuration
Set `"kiwixurl"` in `controldata/default.json` to the Kiwix server base URL, e.g.:
```json
{ "kiwixurl": "http://192.168.1.33:8080" }
```
If absent, both functions return a descriptive error string.

## Parameters

### `kiwix_search(query, max_results=5, timeout=15)`
- `query` *(required)* - search terms to look up across all installed Kiwix books.
- `max_results` *(optional, default 5, max 20)* - number of results to return.
- `timeout` *(optional, default 15)* - network timeout in seconds.

Returns a list of dicts:
```json
[{
  "rank": 1,
  "title": "Python (programming language)",
  "article_path": "/content/wikipedia_en_all_maxi_2025-08/Python_(programming_language)",
  "snippet": "Python is a high-level, general-purpose programming language...",
  "book": "wikipedia_en_all_maxi_2025-08"
}]
```

### `kiwix_get_article(article_path, max_words=600, timeout=15)`
- `article_path` *(required)* - the path from a `kiwix_search` result, e.g. `/content/wikipedia_en_all_maxi_2025-08/Python_(programming_language)`.
- `max_words` *(optional, default 600, max 3000)* - word cap on returned text.
- `timeout` *(optional, default 15)* - network timeout in seconds.

Returns plain text with Markdown headings preserved. Returns an error string on failure.

## Tool selection guidance

**Prefer Kiwix over WebSearch for encyclopaedic and reference topics.**
Kiwix is local, instant, and never rate-limited. For any factual question where a Wikipedia
or Gutenberg article covers the topic, Kiwix is the first choice.

**Prefer Kiwix over `lookup_wikipedia` when Kiwix is configured.**
`kiwix_search` + `kiwix_get_article` retrieves the full article text from the local snapshot
(including the August 2025 maxi edition) rather than the short REST API extract.
Use `lookup_wikipedia` only when `kiwixurl` is not set in default.json.

**Prefer Kiwix over `fetch_page_text` with Wikipedia URLs.**
Never use `fetch_page_text("https://en.wikipedia.org/...")` when Kiwix is available.
Search Kiwix first, then use `kiwix_get_article` with the returned path.

**Workflow: search then fetch.**
Always call `kiwix_search` first to find the correct `article_path`, then call
`kiwix_get_article` with that path. Do not guess article paths.

**Use the scratchpad for large articles.**
Articles can be several hundred words. When the content will be used in a downstream step,
park it with `scratch_save` first to avoid re-fetching.

## Installed books (example)
The available books depend on what ZIM files the server has. Common installations include:
- `wikipedia_en_all_maxi_*` - full English Wikipedia with images
- `wikipedia_en_all_mini_*` - English Wikipedia text-only
- `gutenberg_en_all_*` - Project Gutenberg full English library
- `gutenberg_en_lcc-*` - Gutenberg by Library of Congress classification

## Examples
```
kiwix_search("transformer attention mechanism") 
  -> returns list of article references

kiwix_get_article("/content/wikipedia_en_all_maxi_2025-08/Attention_(machine_learning)", max_words=800)
  -> returns article text
```

**Two-step workflow:**
1. `kiwix_search("Python programming language")` - find the article path
2. `kiwix_get_article(article_path)` - retrieve the text
