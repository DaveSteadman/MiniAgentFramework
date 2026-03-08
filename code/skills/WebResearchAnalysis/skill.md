# WebResearchAnalysis Skill

## Purpose
Read mined content from the 01-Mine research stage and produce structured daily intelligence
summaries using an LLM call. Saves the analysis to the 02-Analysis stage for review and
downstream delivery by the WebResearchOutput skill.

The skill makes its own internal LLM call — the agent's confirmation response will be a
short "Saved: ..." string, not the full analysis text (which can be retrieved via
WebResearchOutput's `get_analysis_text` function if needed).

## Interface
- Module: `code/skills/WebResearchAnalysis/web_research_analysis_skill.py`
- Primary functions:
  - `create_daily_summary(domain, date="", topic="", model="120b", num_ctx=131072)`
  - `list_mine_days(domain, max_days=7)`
  - `list_analyses(domain, max_days=7)`

## Input

### `create_daily_summary(domain, date, topic, model, num_ctx)`
- `domain`: research domain label — must match the domain used during mining (required)
- `date`: date to analyse — accepts `"YYYY-MM-DD"`, `"today"`, `"yesterday"`, or `""` for today
- `topic`: optional context hint for the analyst, e.g. `"AI hardware releases"` or
  `"machine learning papers"`; if provided, the LLM uses it to frame the briefing
- `model`: Ollama model alias or full name; short aliases like `"120b"` or `"20b"` are
  resolved automatically; default `"120b"`
- `num_ctx`: LLM context window in tokens; default `131072` (128K — suitable for 10+ articles)

### `list_mine_days(domain, max_days)`
- `domain`: research domain label (required)
- `max_days`: how many dates to show, oldest-newest, 1–30, default `7`

### `list_analyses(domain, max_days)`
- `domain`: research domain label (required)
- `max_days`: how many dates to show, 1–30, default `7`

## Output

### `create_daily_summary`
On success: `"Saved: <path>\n  (N document(s) analysed, N words written)"`

The saved `analysis.md` contains:
```markdown
# Daily Research Summary: <domain> — <date>

**Generated:** YYYY-MM-DD HH:MM
**Documents analysed:** N
**Model:** <model>

---

## Executive Summary
- ...

## Main Stories
### Story heading
...
**Source:** Article title

## Notable Data Points
- ...

## Overall Assessment
...
```

On failure: a descriptive error string beginning with `Error:` — never raises.

### `list_mine_days`
Multi-line string listing dates with article and results-file counts, newest first.
Example:
```
Mined content available for domain 'AINews':
  2026-03-08:  5 article file(s), 2 search results file(s)
  2026-03-07:  3 article file(s)
```

### `list_analyses`
Multi-line string listing dates with analysis file counts, newest first.

## Saved file structure
```
webresearch/02-Analysis/<domain>/yyyy/mm/dd/NNN-daily-summary/analysis.md
```

## Examples
```python
# Analyse today's AI news mining session
create_daily_summary("AINews", date="today", topic="AI model releases and benchmarks")

# Check what dates have mined content
list_mine_days("AINews", max_days=14)

# Check what analyses have been completed
list_analyses("AINews", max_days=7)

# Analyse a specific historical date with a different model
create_daily_summary("CarIndustry", date="2026-03-07", topic="electric vehicles", model="20b")
```
