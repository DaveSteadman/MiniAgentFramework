# KoreAnalysis Skill

- Module: `code/skills/KoreAnalysis/kore_analysis_skill.py`

## Trigger keyword: KoreAnalysis

When the user includes **KoreAnalysis** in their message, use this skill. Do not use any other summarisation, LLM, or file-writing tool for research analysis tasks.

## Purpose

Read already-mined content from `01-Mine` and produce a structured daily intelligence summary saved to `02-Analysis`. 
No other content is to be used, no additional web search tools.
Makes its own internal LLM call - the agent response will be a short `"Saved: ..."` confirmation, not the full analysis text.

## Usage

**Always call `create_daily_summary` directly.** Do not call any listing function first - `create_daily_summary` returns a descriptive error string if there is nothing to analyse.

## Functions

- `create_daily_summary(domain, date="", topic="")` - read mined files and write `analysis.md`

Do not call list_mine_days or list_analyses as part of a pipeline step - they are diagnostic only.

## Parameters for create_daily_summary

- `domain`: research domain label - must match what was used in KoreMine (required)
- `date`: `"YYYY-MM-DD"`, `"today"`, `"yesterday"`, or `""` for today
- `topic`: optional framing hint, e.g. `"UK and Irish general news - headlines, politics, economics"`

The model and context window are inherited from the running session.

## Output

Saved file: `webresearch/02-Analysis/<domain>/yyyy/mm/dd/analysis.md`

Return value: `"Saved: <path>  (N documents analysed, N words written)"` on success, `"Error: ..."` on failure.

## Pipeline position

```
KoreMine  ->  KoreAnalysis  ->  KoreReport
```
