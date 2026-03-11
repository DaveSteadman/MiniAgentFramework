# WebResearchReport Skill

## Overview

Reads an analysis file produced by **WebResearchAnalysis** and renders it as a polished, self-contained HTML report saved to the `03-Presentation` research stage.

All HTML template and Markdown-to-HTML conversion logic lives in this skill. **WebResearchOutput** (email/SFTP dispatch) has no knowledge of styling - it simply reads the finished HTML file this skill produces.

---

## Workflow position

```
01-Mine  →  02-Analysis  →  03-Presentation  →  dispatch
          (Analysis)      (this skill)       (Output)
```

**Prerequisites**: Run `WebResearchAnalysis.create_daily_summary` first to produce `analysis.md`.

---

## Module

`code/skills/WebResearchReport/web_research_report_skill.py`

---

## Functions

### `save_html_report(domain, date="", template="default")`

Renders the analysis Markdown for `domain`/`date` into a styled standalone HTML file and saves it to `03-Presentation`.

| Parameter  | Type   | Default     | Description |
|------------|--------|-------------|-------------|
| `domain`   | string | required    | Research domain label (e.g. `"GeneralNews"`) |
| `date`     | string | `""` (today)| `YYYY-MM-DD`, `"today"`, `"yesterday"`, or `""` |
| `template` | string | `"default"` | Template variant: `"default"` (light) or `"dark"` |

**Saved to:** `webresearch/03-Presentation/<domain>/yyyy/mm/dd/NNN-daily-report/report.html`

**Returns:** `"Saved: <path>  (N words from analysis)"` on success, or `"Error: ..."` on failure.

**HTML report features:**
- Self-contained - no external dependencies, works offline
- Print-friendly with `@media print` styles
- Responsive for mobile (`@media (max-width: 640px)`)
- Dark header bar with domain name and date
- Styled headings, blockquotes, lists, inline code, links

---

### `get_analysis_text(domain, date="")`

Returns the raw Markdown text of `analysis.md` for the given domain and date. Useful for previewing content before rendering or for the LLM to read and summarise.

| Parameter | Type   | Default     | Description |
|-----------|--------|-------------|-------------|
| `domain`  | string | required    | Research domain label |
| `date`    | string | `""` (today)| `YYYY-MM-DD`, `"today"`, `"yesterday"`, or `""` |

**Returns:** Full Markdown text, or `"Error: ..."`.

---

### `get_report_html(domain, date="")`

Returns the rendered HTML content of the saved report. Run `save_html_report` first.

| Parameter | Type   | Default     | Description |
|-----------|--------|-------------|-------------|
| `domain`  | string | required    | Research domain label |
| `date`    | string | `""` (today)| `YYYY-MM-DD`, `"today"`, `"yesterday"`, or `""` |

**Returns:** Full HTML string, or `"Error: ..."`.

---

### `list_reports(domain, max_days=7)`

Lists available HTML reports in `03-Presentation` for a domain, newest first.

| Parameter  | Type | Default | Description |
|------------|------|---------|-------------|
| `domain`   | string | required | Research domain label |
| `max_days` | int  | `7`     | Maximum number of dated entries to return |

**Returns:** Formatted list string, or `"Error: ..."`.

---

## Example prompts

```
Save an HTML report for the GeneralNews domain for today
```
```
Save an HTML report for domain AINews for yesterday
```
```
List available reports for GeneralNews
```
```
Show me the analysis text for GeneralNews today
```

---

## Full pipeline

```
Mine UK news headlines for today into the GeneralNews domain
Mine French news headlines for today into the GeneralNews domain
Mine German news headlines for today into the GeneralNews domain
Create a daily research summary for GeneralNews for today covering the top 10 most significant stories with 500 words on each
Save an HTML report for the GeneralNews domain for today
Send the GeneralNews report for today to the default mailing list
```
