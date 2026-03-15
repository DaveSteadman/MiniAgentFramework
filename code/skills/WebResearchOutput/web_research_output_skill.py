# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebResearchOutput skill for MiniAgentFramework.
#
# Dispatches rendered reports from the 03-Presentation research stage to external
# destinations.  This skill handles the mechanics of delivery only - HTML rendering
# and template styling are handled entirely by KoreReport.
#
# Supported destinations:
#   Email   -- send_report_email()   -- SMTP STARTTLS delivery to a configured mailing list
#
# Future destinations (not yet implemented):
#   SFTP    -- upload_report_sftp()  -- upload report.html to a remote server
#
# Email configuration is stored in:
#   controldata/email_config.json
#
# SMTP credentials are NEVER stored in the config file.  Instead, the config specifies the
# name of an environment variable that holds the password - e.g. "MINIAGENT_SMTP_PASSWORD".
# Set this env var before running (e.g. $env:MINIAGENT_SMTP_PASSWORD = "your_password").
#
# Primary public functions:
#   send_report_email(domain, date="", list_name="default", subject="")
#     -> Reads report.html from 03-Presentation for domain/date, sends it as an HTML email
#        to the named mailing list.
#        Returns "Sent to N recipient(s): ..." on success or an "Error: ..." string.
#
#   list_reports(domain, max_days=7)
#     -> Lists available report dates in 03-Presentation for a domain.
#
# Related modules:
#   - webresearch_utils.py               -- path management for all research stages
#   - workspace_utils.py                 -- provides get_controldata_dir()
#   - skills/KoreReport/                 -- produces the 03-Presentation HTML consumed here
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import os
import re
import smtplib
from datetime import date as _date, datetime as _datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from prompt_tokens import parse_flexible_date as _parse_date
from webresearch_utils import STAGE_PRESENTATION, get_domain_dir, get_date_dir
from workspace_utils import get_controldata_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_EMAIL_CONFIG_PATH = get_controldata_dir() / "email_config.json"

PLANNER_TOOLS = [
    {
        "name": "web_research_output.send_report_email",
        "function": "send_report_email",
        "description": "Send a saved KoreReport HTML report by email to a configured mailing list.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Research domain label used by the report."},
                "date": {"type": "string", "description": "Report date as YYYY-MM-DD, today, yesterday, or empty for today."},
                "list_name": {"type": "string", "description": "Configured mailing list key in controldata/email_config.json."},
                "subject": {"type": "string", "description": "Optional email subject line override."},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "web_research_output.list_reports",
        "function": "list_reports",
        "description": "List available rendered HTML reports in the 03-Presentation stage for a domain.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Research domain label used by the report."},
                "max_days": {"type": "number", "description": "Maximum number of dated report entries to return."},
            },
            "required": ["domain"],
        },
    },
]



# ====================================================================================================
# MARK: EMAIL CONFIG LOADER
# ====================================================================================================
def _load_email_config() -> dict:
    """Load and return the email config dict.  Raises FileNotFoundError / ValueError on problems."""
    if not _EMAIL_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Email config not found: {_EMAIL_CONFIG_PATH}\n"
            f"Create this file - see controldata/email_config.json for the template."
        )
    with _EMAIL_CONFIG_PATH.open(encoding="utf-8") as fh:
        config = json.load(fh)

    required = ["smtp_host", "smtp_port", "smtp_user", "smtp_password_env", "from_address", "mailing_lists"]
    missing  = [k for k in required if k not in config]
    if missing:
        raise ValueError(f"email_config.json is missing required keys: {missing}")

    return config


# ====================================================================================================
# MARK: REPORT FILE LOCATOR
# ====================================================================================================
def _find_report_file(domain: str, when: _date) -> Path | None:
    """Return report.html under 03-Presentation/<domain>/yyyy/mm/dd/, or None."""
    path = get_date_dir(STAGE_PRESENTATION, domain, when) / "report.html"
    return path if path.exists() else None


# ====================================================================================================
# MARK: DATE DIRECTORY ITERATOR
# ====================================================================================================
def _iter_date_dirs(domain: str, max_days: int) -> list[tuple[_date, Path]]:
    domain_dir = get_domain_dir(STAGE_PRESENTATION, domain)
    if not domain_dir.exists():
        return []
    entries: list[tuple[_date, Path]] = []
    for year_dir in sorted(domain_dir.iterdir(), reverse=True):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for day_dir in sorted(month_dir.iterdir(), reverse=True):
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                try:
                    d = _date(int(year_dir.name), int(month_dir.name), int(day_dir.name))
                except ValueError:
                    continue
                entries.append((d, day_dir))
                if len(entries) >= max_days:
                    return entries
    return entries


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def send_report_email(
    domain: str,
    date: str = "",
    list_name: str = "default",
    subject: str = "",
) -> str:
    """Send the HTML report for domain/date to a configured mailing list.

    Reads report.html from 03-Presentation (produced by KoreReport.save_html_report)
    and delivers it as an HTML email via SMTP STARTTLS.

    Parameters
    ----------
    domain    : research domain label (required, e.g. "GeneralNews")
    date      : YYYY-MM-DD, "today", "yesterday", or "" for today
    list_name : key in email_config.json -> mailing_lists; default "default"
    subject   : email subject line; auto-generated as "domain Report -- YYYY-MM-DD" if empty

    Returns "Sent to N recipient(s): ..." on success.
    Returns a descriptive "Error: ..." string on failure -- never raises.

    Prerequisites:
      - controldata/email_config.json must exist and be configured
      - The environment variable named by smtp_password_env must be set
      - KoreReport.save_html_report must have been run first
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        when = _parse_date(date)
    except ValueError:
        return f"Error: invalid date {date!r}. Use YYYY-MM-DD, 'today', or 'yesterday'."

    report_path = _find_report_file(domain.strip(), when)
    if report_path is None:
        date_label = when.strftime("%Y/%m/%d")
        return (
            f"Error: no report.html found under 03-Presentation/{domain}/{date_label}/\n"
            f"Run KoreReport.save_html_report first."
        )

    try:
        html_body = report_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: could not read report file: {exc}"

    try:
        config = _load_email_config()
    except (FileNotFoundError, ValueError) as exc:
        return f"Error: {exc}"

    mailing_lists = config.get("mailing_lists", {})
    recipients    = mailing_lists.get(list_name)
    if not recipients:
        available = list(mailing_lists.keys())
        return (
            f"Error: mailing list '{list_name}' not found in email_config.json.\n"
            f"Available lists: {available}"
        )

    password_env = config.get("smtp_password_env", "")
    password     = os.environ.get(password_env, "")
    if not password:
        return (
            f"Error: SMTP password environment variable '{password_env}' is not set.\n"
            f"Set it before sending: $env:{password_env} = 'your_password'"
        )

    if not subject or not subject.strip():
        subject = f"{domain} Report - {when.strftime('%Y-%m-%d')}"

    # Plain-text fallback: strip tags for clients that prefer text/plain.
    import re as _re
    plain_text = _re.sub(r"<[^>]+>", " ", html_body)
    plain_text = _re.sub(r" {2,}", " ", plain_text).strip()

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config["from_address"]
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    try:
        with smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(config["smtp_user"], password)
            server.sendmail(config["from_address"], recipients, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        return "Error: SMTP authentication failed - check smtp_user and the password env var."
    except smtplib.SMTPException as exc:
        return f"Error: SMTP error: {exc}"
    except OSError as exc:
        return f"Error: could not connect to {config['smtp_host']}:{config['smtp_port']}: {exc}"

    n = len(recipients)
    return f"Sent to {n} recipient(s): {', '.join(recipients)}\n  Subject: {subject}"


# ----------------------------------------------------------------------------------------------------
def list_reports(domain: str, max_days: int = 7) -> str:
    """List available HTML reports in 03-Presentation for a domain, newest first.

    Returns a formatted multi-line string, or an error string.  Never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        entries = _iter_date_dirs(domain.strip(), max(1, int(max_days)))
    except Exception as exc:
        return f"Error: {exc}"

    if not entries:
        return f"No reports found for domain '{domain}'."

    lines = [f"Available reports for domain '{domain}':"]
    for d, day_dir in entries:
        exists = (day_dir / "report.html").exists()
        lines.append(f"  {d.strftime('%Y-%m-%d')}:  {'1 report file' if exists else 'no report file'}")
    return "\n".join(lines)
