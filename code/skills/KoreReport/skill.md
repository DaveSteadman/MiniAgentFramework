# KoreReport Skill

- Module: `code/skills/KoreReport/kore_report_skill.py`

## Trigger keyword: KoreReport

When the user includes **KoreReport** in their message, use this skill. Do NOT use `write_text_file` or any other file-writing tool - this skill handles all HTML generation and file saving internally.

## Purpose

Read an `analysis.md` produced by KoreAnalysis and render it as a polished, self-contained HTML report saved to `03-Presentation`. All templating and Markdown-to-HTML conversion is handled internally.

## Functions

- `save_html_report(domain, date="", template="default")` - render and save the HTML report
- `get_analysis_text(domain, date="")` - return the raw analysis Markdown text
- `get_report_html(domain, date="")` - return the saved HTML string
- `list_reports(domain, max_days=7)` - list available reports for a domain

## Parameters for save_html_report

- `domain`: research domain label - must match what was used in KoreMine / KoreAnalysis (required)
- `date`: `"YYYY-MM-DD"`, `"today"`, `"yesterday"`, or `""` for today
- `template`: `"default"` (light) or `"dark"`

## Output

Saved file: `webresearch/03-Presentation/<domain>/yyyy/mm/dd/NNN-daily-report/report.html`

Return value: `"Saved: <path>  (N words from analysis)"` on success, `"Error: ..."` on failure.

## Pipeline position

```
KoreMine  ->  KoreAnalysis  ->  KoreReport
```
