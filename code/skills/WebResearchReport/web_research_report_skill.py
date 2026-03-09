# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebResearchReport skill for MiniAgentFramework.
#
# Reads analysis files from the 02-Analysis research stage, converts them to a styled
# standalone HTML report, and saves the result to the 03-Presentation research stage.
# All HTML template and formatting logic lives here — WebResearchOutput (email/SFTP
# dispatch) has no knowledge of styling or conversion.
#
# Primary public functions:
#   save_html_report(domain, date="", template="default")
#     -> Reads analysis.md for domain/date, renders to styled HTML, saves to
#        03-Presentation/<domain>/yyyy/mm/dd/NNN-daily-report/report.html.
#        Returns "Saved: <path>" on success or an "Error: ..." string.
#
#   get_analysis_text(domain, date="")
#     -> Returns the raw Markdown text of the analysis.md for agent/LLM review.
#
#   get_report_html(domain, date="")
#     -> Returns the rendered HTML of the saved report for preview.
#
#   list_reports(domain, max_days=7)
#     -> Lists available report dates in 03-Presentation, newest first.
#
# Related modules:
#   - webresearch_utils.py               -- path management for all research stages
#   - skills/WebResearchAnalysis/        -- produces the 02-Analysis content consumed here
#   - skills/WebResearchOutput/          -- consumes 03-Presentation reports for dispatch
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html_module
import re
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from prompt_tokens import parse_flexible_date as _parse_date
from webresearch_utils import (
    STAGE_ANALYSIS,
    STAGE_PRESENTATION,
    get_domain_dir,
    get_date_dir,
    create_item_dir,
)


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SPACE_RE = re.compile(r"\s+")


# ====================================================================================================
# MARK: HTML REPORT TEMPLATE
# ====================================================================================================
# Self-contained standalone HTML — no external dependencies, print-friendly.
_REPORT_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body         {{ font-family: Georgia, 'Times New Roman', serif;
                    background: #f7f7f5; color: #222; margin: 0; padding: 0; }}
    .rpt-header  {{ background: #0d1b2a; color: #fff; padding: 28px 40px; }}
    .rpt-title   {{ font-size: 1.75em; font-weight: bold;
                    font-family: Arial, Helvetica, sans-serif; letter-spacing: 0.01em; }}
    .rpt-meta    {{ margin-top: 8px; font-size: 0.85em; color: #9bbdd4;
                    font-family: Arial, Helvetica, sans-serif; }}
    .content     {{ max-width: 880px; margin: 0 auto; padding: 36px 40px; }}
    h1 {{ color: #0d1b2a; border-bottom: 3px solid #2d7dd2; padding-bottom: 10px;
          font-size: 1.55em; margin-top: 40px; font-family: Arial, Helvetica, sans-serif; }}
    h2 {{ color: #0d1b2a; margin-top: 40px; font-size: 1.25em;
          border-left: 4px solid #2d7dd2; padding-left: 12px;
          font-family: Arial, Helvetica, sans-serif; }}
    h3 {{ color: #1a5276; font-size: 1.1em; margin-top: 28px;
          font-family: Arial, Helvetica, sans-serif; }}
    h4 {{ color: #555; font-size: 1em; font-family: Arial, Helvetica, sans-serif; }}
    p  {{ margin: 12px 0; line-height: 1.85; }}
    ul, ol {{ padding-left: 26px; }}
    li {{ margin-bottom: 6px; line-height: 1.75; }}
    strong {{ color: #0d1b2a; }}
    em     {{ color: #444; }}
    a      {{ color: #2d7dd2; }}
    hr  {{ border: none; border-top: 1px solid #dde; margin: 36px 0; }}
    blockquote {{ border-left: 4px solid #2d7dd2; padding: 8px 18px;
                  color: #555; margin: 18px 0; font-style: italic; background: #f0f4fa; }}
    code {{ background: #eef; padding: 2px 6px; border-radius: 3px;
            font-size: 0.88em; font-family: 'Courier New', Courier, monospace; }}
    .rpt-footer {{ max-width: 880px; margin: 0 auto; padding: 20px 40px 40px;
                   font-size: 0.78em; color: #aaa; border-top: 1px solid #dde;
                   font-family: Arial, Helvetica, sans-serif; }}
    @media (max-width: 640px) {{
      .rpt-header, .content, .rpt-footer {{ padding-left: 18px; padding-right: 18px; }}
    }}
    @media print {{
      body {{ background: white; }}
      .rpt-header {{ background: #0d1b2a !important; -webkit-print-color-adjust: exact;
                     print-color-adjust: exact; }}
    }}
  </style>
</head>
<body>
<div class="rpt-header">
  <div class="rpt-title">{domain} &mdash; Research Report</div>
  <div class="rpt-meta">{date_label} &nbsp;&mdash;&nbsp; Generated {generated}</div>
</div>
<div class="content">
{body}
</div>
<div class="rpt-footer">Generated by MiniAgentFramework</div>
</body>
</html>"""


# ----------------------------------------------------------------------------------------------------
_REPORT_HTML_TEMPLATE_DARK = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
      background: #000;
      color: rgba(255,255,255,0.87);
      margin: 0;
      padding: 0;
    }}
    .rpt-header {{
      position: sticky; top: 0; z-index: 50;
      border-bottom: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.90);
      backdrop-filter: blur(12px);
      padding: 14px 40px;
      display: flex; align-items: center; justify-content: space-between;
    }}
    .rpt-logo-mark {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 40px; height: 40px;
      border: 1px solid rgba(255,255,255,0.20);
      background: #09090b;
      margin-right: 14px; flex-shrink: 0;
    }}
    .rpt-logo-mark-inner {{
      width: 18px; height: 18px;
      border: 1px solid rgba(255,255,255,0.60);
      transform: rotate(45deg);
    }}
    .rpt-brand {{ display: flex; align-items: center; }}
    .rpt-brand-sub {{
      font-size: 10px; letter-spacing: 0.35em;
      text-transform: uppercase; color: rgba(255,255,255,0.45);
    }}
    .rpt-brand-name {{
      font-size: 14px; font-weight: 600;
      letter-spacing: 0.15em; text-transform: uppercase;
    }}
    .rpt-date-badge {{
      font-size: 10px; letter-spacing: 0.25em;
      text-transform: uppercase; color: rgba(255,255,255,0.55);
      border: 1px solid rgba(255,255,255,0.15);
      padding: 6px 14px;
    }}
    .rpt-hero {{
      position: relative;
      border-bottom: 1px solid rgba(255,255,255,0.10);
      overflow: hidden;
      padding: 52px 40px;
      background-image:
        linear-gradient(135deg, rgba(255,255,255,0.05) 1px, transparent 1px),
        linear-gradient(315deg, rgba(255,255,255,0.03) 1px, transparent 1px);
      background-size: 48px 48px;
    }}
    .rpt-hero::before {{
      content: ''; position: absolute; inset: 0;
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.08), transparent 28%),
        radial-gradient(circle at bottom left, rgba(255,255,255,0.04), transparent 22%);
    }}
    .rpt-hero-inner {{ position: relative; max-width: 880px; margin: 0 auto; }}
    .rpt-eyebrow {{
      display: inline-flex; align-items: center; gap: 10px;
      border: 1px solid rgba(255,255,255,0.15);
      background: rgba(255,255,255,0.05);
      padding: 6px 14px;
      font-size: 10px; letter-spacing: 0.28em;
      text-transform: uppercase; color: rgba(255,255,255,0.65);
      margin-bottom: 20px;
    }}
    .rpt-eyebrow-dot {{
      width: 7px; height: 7px;
      background: white; transform: rotate(45deg); flex-shrink: 0;
    }}
    .rpt-domain {{
      font-size: 44px; font-weight: 700;
      letter-spacing: 0.04em; text-transform: uppercase;
      line-height: 0.95;
    }}
    .rpt-domain-sub {{
      display: block; color: rgba(255,255,255,0.45); margin-top: 4px;
    }}
    .rpt-meta-row {{
      margin-top: 16px; font-size: 12px;
      color: rgba(255,255,255,0.40); letter-spacing: 0.06em;
    }}
    .content {{ max-width: 880px; margin: 0 auto; padding: 44px 40px 64px; }}
    h1 {{
      font-size: 20px; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase;
      color: white;
      border-left: 3px solid rgba(255,255,255,0.35);
      padding-left: 14px;
      margin-top: 52px; margin-bottom: 16px;
    }}
    h2 {{
      font-size: 15px; font-weight: 600;
      letter-spacing: 0.10em; text-transform: uppercase;
      color: rgba(255,255,255,0.88);
      border-left: 2px solid rgba(255,255,255,0.20);
      padding-left: 12px;
      margin-top: 38px; margin-bottom: 10px;
    }}
    h3 {{
      font-size: 12px; font-weight: 600;
      letter-spacing: 0.18em; text-transform: uppercase;
      color: rgba(255,255,255,0.60);
      margin-top: 28px; margin-bottom: 8px;
    }}
    h4 {{
      font-size: 11px; font-weight: 600;
      letter-spacing: 0.22em; text-transform: uppercase;
      color: rgba(255,255,255,0.38);
      margin-top: 20px;
    }}
    p {{
      margin: 10px 0; line-height: 1.82;
      font-size: 14px; color: rgba(255,255,255,0.72);
    }}
    ul, ol {{ padding-left: 0; list-style: none; margin: 12px 0; }}
    li {{
      padding: 8px 12px 8px 22px;
      border-left: 1px solid rgba(255,255,255,0.10);
      margin-bottom: 4px;
      font-size: 14px; line-height: 1.65;
      color: rgba(255,255,255,0.72);
      position: relative;
    }}
    li::before {{
      content: '';
      position: absolute; left: 8px; top: 15px;
      width: 5px; height: 5px;
      background: rgba(255,255,255,0.35);
      transform: rotate(45deg);
    }}
    strong {{ color: white; }}
    em     {{ color: rgba(255,255,255,0.72); }}
    a      {{ color: rgba(255,255,255,0.80); }}
    hr     {{ border: none; border-top: 1px solid rgba(255,255,255,0.10); margin: 44px 0; }}
    blockquote {{
      border-left: 3px solid rgba(255,255,255,0.25);
      padding: 10px 20px;
      color: rgba(255,255,255,0.55);
      margin: 20px 0;
      background: rgba(255,255,255,0.03);
      font-style: italic;
    }}
    code {{
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.12);
      padding: 2px 7px; font-size: 0.85em;
      font-family: 'Courier New', Courier, monospace;
    }}
    .rpt-footer {{
      max-width: 880px; margin: 0 auto;
      padding: 16px 40px 32px;
      border-top: 1px solid rgba(255,255,255,0.08);
      font-size: 10px; letter-spacing: 0.22em;
      text-transform: uppercase; color: rgba(255,255,255,0.22);
    }}
    @media (max-width: 640px) {{
      .rpt-header, .rpt-hero, .content, .rpt-footer {{ padding-left: 18px; padding-right: 18px; }}
      .rpt-domain {{ font-size: 30px; }}
    }}
    @media print {{
      .rpt-header {{ position: static; }}
      body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
  </style>
</head>
<body>
<header class="rpt-header">
  <div class="rpt-brand">
    <div class="rpt-logo-mark"><div class="rpt-logo-mark-inner"></div></div>
    <div>
      <div class="rpt-brand-sub">Research Intelligence</div>
      <div class="rpt-brand-name">MiniAgent</div>
    </div>
  </div>
  <div class="rpt-date-badge">{date_label}</div>
</header>
<section class="rpt-hero">
  <div class="rpt-hero-inner">
    <div class="rpt-eyebrow"><span class="rpt-eyebrow-dot"></span>Daily Report</div>
    <div class="rpt-domain">{domain}<span class="rpt-domain-sub">Research Summary</span></div>
    <div class="rpt-meta-row">Generated {generated}</div>
  </div>
</section>
<div class="content">
{body}
</div>
<div class="rpt-footer">Generated by MiniAgentFramework</div>
</body>
</html>"""

_TEMPLATES = {
    "default": _REPORT_HTML_TEMPLATE,
    "dark":    _REPORT_HTML_TEMPLATE_DARK,
}


# ====================================================================================================
# MARK: MARKDOWN TO HTML
# ====================================================================================================
def _md_to_html(md_text: str) -> str:
    """Convert Markdown to HTML using the `markdown` package if available, else fallback."""
    try:
        import markdown  # type: ignore
        return markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code", "nl2br"],
        )
    except ImportError:
        pass
    return _md_to_html_fallback(md_text)


def _md_to_html_fallback(md_text: str) -> str:
    """Minimal regex-based Markdown→HTML converter.

    Handles ATX headings (# to ####), bold, italic, inline code, links,
    bullet lists, horizontal rules, and blank-line paragraph breaks.
    Sufficient for the analysis.md output format.
    """
    lines: list[str]     = md_text.splitlines()
    html_lines: list[str] = []
    in_ul = False
    in_p  = False

    def close_open_blocks() -> None:
        nonlocal in_ul, in_p
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_p:
            html_lines.append("</p>")
            in_p = False

    def inline(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
        text = re.sub(r"`(.+?)`",       r"<code>\1</code>",     text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        return text

    for raw in lines:
        line = raw.rstrip()

        if re.match(r"^-{3,}$|^_{3,}$|^\*{3,}$", line):
            close_open_blocks()
            html_lines.append("<hr>")
            continue

        hm = re.match(r"^(#{1,4})\s+(.*)", line)
        if hm:
            close_open_blocks()
            lvl  = len(hm.group(1))
            text = inline(_html_module.escape(hm.group(2)))
            html_lines.append(f"<h{lvl}>{text}</h{lvl}>")
            continue

        bm = re.match(r"^[-*]\s+(.*)", line)
        if bm:
            if in_p:
                html_lines.append("</p>")
                in_p = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            text = inline(_html_module.escape(bm.group(1)))
            html_lines.append(f"  <li>{text}</li>")
            continue

        if not line.strip():
            close_open_blocks()
            continue

        close_open_blocks()
        text = inline(_html_module.escape(line))
        html_lines.append(f"<p>{text}")
        in_p = True

    close_open_blocks()
    return "\n".join(html_lines)


# ====================================================================================================
# MARK: HTML BUILDER
# ====================================================================================================
def _build_report_html(domain: str, when: _date, body_md: str, template: str = "default") -> str:
    """Render analysis Markdown into the styled standalone HTML report template."""
    now        = _datetime.now().strftime("%Y-%m-%d %H:%M")
    date_label = when.strftime("%A, %d %B %Y")
    title      = f"{domain} Research Report — {when.strftime('%Y-%m-%d')}"
    body_html  = _md_to_html(body_md)
    tmpl       = _TEMPLATES.get(template, _REPORT_HTML_TEMPLATE)
    return tmpl.format(
        title      = title,
        domain     = domain,
        date_label = date_label,
        generated  = now,
        body       = body_html,
    )


# ====================================================================================================
# MARK: ANALYSIS FILE LOCATOR
# ====================================================================================================
def _find_analysis_file(domain: str, when: _date) -> Path | None:
    """Return the most recent analysis.md under 02-Analysis/<domain>/yyyy/mm/dd/, or None."""
    date_dir = get_date_dir(STAGE_ANALYSIS, domain, when)
    if not date_dir.exists():
        return None
    candidates = sorted(date_dir.rglob("analysis.md"))
    return candidates[-1] if candidates else None


# ====================================================================================================
# MARK: REPORT FILE LOCATOR
# ====================================================================================================
def _find_report_file(domain: str, when: _date) -> Path | None:
    """Return the most recent report.html under 03-Presentation/<domain>/yyyy/mm/dd/, or None."""
    date_dir = get_date_dir(STAGE_PRESENTATION, domain, when)
    if not date_dir.exists():
        return None
    candidates = sorted(date_dir.rglob("report.html"))
    return candidates[-1] if candidates else None


# ====================================================================================================
# MARK: DATE DIRECTORY ITERATOR
# ====================================================================================================
def _iter_date_dirs(stage: str, domain: str, max_days: int) -> list[tuple[_date, Path]]:
    domain_dir = get_domain_dir(stage, domain)
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
def save_html_report(domain: str, date: str = "", template: str = "default") -> str:
    """Render the analysis for domain/date as a styled HTML file and save it to 03-Presentation.

    Parameters
    ----------
    domain   : research domain label (required, e.g. "GeneralNews")
    date     : YYYY-MM-DD, "today", "yesterday", or "" (defaults to today)
    template : reserved for future use; currently only "default" is supported

    The report is saved to:
      webresearch/03-Presentation/<domain>/yyyy/mm/dd/NNN-daily-report/report.html

    Returns "Saved: <path>  (N words)" on success.
    Returns a descriptive "Error: ..." string on failure — never raises.

    Prerequisite: run WebResearchAnalysis.create_daily_summary first to produce analysis.md.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        when = _parse_date(date)
    except ValueError:
        return f"Error: invalid date {date!r}. Use YYYY-MM-DD, 'today', or 'yesterday'."

    analysis_path = _find_analysis_file(domain.strip(), when)
    if analysis_path is None:
        date_label = when.strftime("%Y/%m/%d")
        return (
            f"Error: no analysis.md found under 02-Analysis/{domain}/{date_label}/\n"
            f"Run WebResearchAnalysis.create_daily_summary first."
        )

    try:
        analysis_text = analysis_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: could not read analysis file: {exc}"

    html_content = _build_report_html(domain.strip(), when, analysis_text, template)

    try:
        item_dir    = create_item_dir(STAGE_PRESENTATION, domain.strip(), "daily-report", when)
        report_path = item_dir / "report.html"
        report_path.write_text(html_content, encoding="utf-8")
    except Exception as exc:
        return f"Error: could not write report file: {exc}"

    word_count = len(analysis_text.split())
    return f"Saved: {report_path}\n  ({word_count} words from analysis)"


# ----------------------------------------------------------------------------------------------------
def get_analysis_text(domain: str, date: str = "") -> str:
    """Return the raw Markdown text of the analysis.md for the given domain and date.

    Useful for reviewing the analysis before rendering or sending.
    Returns the full analysis text on success, or an "Error: ..." string.  Never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        when = _parse_date(date)
    except ValueError:
        return f"Error: invalid date {date!r}. Use YYYY-MM-DD, 'today', or 'yesterday'."

    analysis_path = _find_analysis_file(domain.strip(), when)
    if analysis_path is None:
        date_label = when.strftime("%Y/%m/%d")
        return (
            f"No analysis found for {domain}/{date_label}. "
            f"Run WebResearchAnalysis.create_daily_summary first."
        )

    try:
        return analysis_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: could not read analysis file: {exc}"


# ----------------------------------------------------------------------------------------------------
def get_report_html(domain: str, date: str = "") -> str:
    """Return the rendered HTML content of the saved report for the given domain and date.

    Returns the full HTML on success, or an "Error: ..." string.  Never raises.
    Run save_html_report first to generate the report file.
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
            f"No report found for {domain}/{date_label}. "
            f"Run save_html_report first."
        )

    try:
        return report_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: could not read report file: {exc}"


# ----------------------------------------------------------------------------------------------------
def list_reports(domain: str, max_days: int = 7) -> str:
    """List available HTML reports in 03-Presentation for a domain, newest first.

    Returns a formatted multi-line string, or an error string.  Never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        entries = _iter_date_dirs(STAGE_PRESENTATION, domain.strip(), max(1, int(max_days)))
    except Exception as exc:
        return f"Error: {exc}"

    if not entries:
        return f"No reports found for domain '{domain}'."

    lines = [f"Available HTML reports for domain '{domain}':"]
    for d, day_dir in entries:
        count = len(list(day_dir.rglob("report.html")))
        lines.append(f"  {d.strftime('%Y-%m-%d')}:  {count} report file(s)")
    return "\n".join(lines)
