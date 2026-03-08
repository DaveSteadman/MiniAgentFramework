# WebResearchOutput Skill

## Overview

Dispatches rendered HTML reports from the `03-Presentation` research stage to external destinations. This skill handles **delivery mechanics only** — HTML rendering and template styling are handled entirely by **WebResearchReport**.

Supported destinations:
- **Email** — SMTP STARTTLS to a configured mailing list (`send_report_email`)

Planned future destinations:
- **SFTP** — upload `report.html` to a remote server

---

## Workflow position

```
01-Mine  →  02-Analysis  →  03-Presentation  →  dispatch
          (Analysis)      (Report)           (this skill)
```

**Prerequisite**: Run `WebResearchReport.save_html_report` first to produce `report.html` in `03-Presentation`.

---

## Module

`code/skills/WebResearchOutput/web_research_output_skill.py`

---

## Functions

### `send_report_email(domain, date="", list_name="default", subject="")`

Reads `report.html` from `03-Presentation` and delivers it as an HTML email via SMTP STARTTLS.

| Parameter   | Type   | Default      | Description |
|-------------|--------|--------------|-------------|
| `domain`    | string | required     | Research domain label (e.g. `"GeneralNews"`) |
| `date`      | string | `""` (today) | `YYYY-MM-DD`, `"today"`, `"yesterday"`, or `""` |
| `list_name` | string | `"default"`  | Key in `email_config.json → mailing_lists` |
| `subject`   | string | `""` (auto)  | Email subject; auto-generated as `"domain Report — YYYY-MM-DD"` if empty |

**Returns:** `"Sent to N recipient(s): ..."` on success, or `"Error: ..."` on failure.

### `list_reports(domain, max_days=7)`

Lists available HTML reports in `03-Presentation` for a domain, newest first.

| Parameter  | Type   | Default  | Description |
|------------|--------|----------|-------------|
| `domain`   | string | required | Research domain label |
| `max_days` | int    | `7`      | Maximum number of dated entries to return |

**Returns:** Formatted list string, or `"Error: ..."`.

---

## Email configuration

Create `controldata/email_config.json`:

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "your_address@gmail.com",
  "smtp_password_env": "MINIAGENT_SMTP_PASSWORD",
  "from_address": "MiniAgent Reports <your_address@gmail.com>",
  "mailing_lists": {
    "default": ["recipient@example.com"],
    "GeneralNews": ["alice@example.com", "bob@example.com"]
  }
}
```

Set the SMTP password before sending (never stored in the config):
```powershell
$env:MINIAGENT_SMTP_PASSWORD = "your_app_password"
```

---

## Example prompts

```
Send the GeneralNews report for today to the default mailing list
```
```
Send the GeneralNews report for today to the GeneralNews mailing list
```
```
List available reports for GeneralNews
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


## Input

### `send_daily_summary(domain, date, list_name, subject)`
- `domain`: research domain label — must match what was used during mining and analysis (required)
- `date`: date of the analysis to send — accepts `"YYYY-MM-DD"`, `"today"`, `"yesterday"`,
  or `""` for today
- `list_name`: key in `email_config.json` → `mailing_lists`; default `"default"`
- `subject`: email subject line; auto-generated as
  `"Daily Research Summary: <domain> — <date>"` if empty

### `get_analysis_text(domain, date)`
- `domain`: research domain label (required)
- `date`: same format as above; default today

### `list_analyses(domain, max_days)`
- `domain`: research domain label (required)
- `max_days`: number of dates to show, 1–30, default `7`

## Output

### `send_daily_summary`
On success: `"Sent to N recipient(s): alice@..., bob@...\n  Subject: ..."`
On failure: a descriptive error string beginning with `Error:` — never raises.

The email is sent as `multipart/alternative` with both plain-text and HTML parts.
HTML is generated using the `markdown` package (if installed) or a minimal inline converter.

### `get_analysis_text`
Returns the full text of the analysis.md file as a string.
Useful for reviewing or summarising the analysis before sending.

### `list_analyses`
Multi-line string listing dates with analysis file counts, newest first.
Example:
```
Completed analyses for domain 'AINews':
  2026-03-08:  1 analysis file(s)
  2026-03-07:  1 analysis file(s)
```

## Email config file: `controldata/email_config.json`
```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "sender@example.com",
  "smtp_password_env": "MINIAGENT_SMTP_PASSWORD",
  "from_address": "MiniAgent Reports <sender@example.com>",
  "mailing_lists": {
    "default": ["recipient@example.com"],
    "AINews":  ["alice@example.com", "bob@example.com"]
  }
}
```

The `smtp_password_env` field holds the **name** of an environment variable,
not the password itself — credentials are never stored in the config file.

## Examples
```python
# List available analyses before sending
list_analyses("AINews", max_days=7)

# Review the analysis text first
get_analysis_text("AINews", date="today")

# Send today's AI news summary to the default mailing list
send_daily_summary("AINews", date="today")

# Send to a specific list with a custom subject
send_daily_summary("AINews", date="2026-03-08", list_name="executives",
                   subject="AI Market Digest — 8 March 2026")
```
