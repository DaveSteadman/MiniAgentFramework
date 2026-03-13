# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebResearchAnalysis skill for MiniAgentFramework.
#
# Reads mined content from the 01-Mine stage and produces structured daily intelligence
# summaries using an LLM call made directly from this skill.  Persists the analysis
# to the 02-Analysis stage so it is available for review and for downstream delivery
# by the WebResearchOutput skill.
#
# Design note: this skill makes its own LLM call (a "thick skill") rather than delegating
# to the agent's final LLM pass.  This is intentional - the summary must be saved to disk
# before the agent responds, and the agent's final LLM context should contain a confirmation
# string, not a bulk research report.  The same pattern is used by skills_catalog_builder.py.
#
# Primary public functions:
#   create_daily_summary(domain, date="", topic="", model="20b", num_ctx=131072)
#     -> Reads all mined .md files for domain/date, calls LLM to produce a structured
#        Markdown analysis, saves it to 02-Analysis, returns "Saved: <path>"
#
#   list_mine_days(domain, max_days=7)
#     -> Returns a human-readable listing of available mined dates for a domain
#
#   list_analyses(domain, max_days=7)
#     -> Returns a human-readable listing of completed analyses for a domain
#
# Saved file location:
#   webresearch/02-Analysis/<domain>/yyyy/mm/dd/analysis.md
#
# Related modules:
#   - webresearch_utils.py               -- path management for all three research stages
#   - ollama_client.py                   -- LLM call and model resolution
#   - skills/WebMine/                    -- produces the 01-Mine content consumed here
#   - skills/WebResearchOutput/          -- consumes 02-Analysis content produced here
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from prompt_tokens import parse_flexible_date as _parse_date
from webresearch_utils import (
    STAGE_MINE,
    STAGE_ANALYSIS,
    get_domain_dir,
    get_date_dir,
    ensure_date_dir,
)
from ollama_client import call_ollama_extended, list_ollama_models, resolve_model_name


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DEFAULT_MODEL   = "20b"
_DEFAULT_NUM_CTX = 131072

_SPACE_RE = re.compile(r"\s+")


# ====================================================================================================
# MARK: MINE STAGE READERS
# ====================================================================================================
def _find_content_files(domain: str, when: _date) -> list[Path]:
    """Return all .md files directly under 01-Mine/<domain>/yyyy/mm/dd/, sorted."""
    date_dir = get_date_dir(STAGE_MINE, domain, when)
    if not date_dir.exists():
        return []
    return sorted(date_dir.glob("*.md"))


def _read_articles(content_files: list[Path]) -> list[dict]:
    """Read each .md file and extract title, url, and body text.

    The returned list preserves the order of content_files.
    Files that cannot be read are silently skipped.
    """
    articles: list[dict] = []
    for path in content_files:
        try:
            text = path.read_text(encoding="utf-8")
            title = ""
            url   = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("# ") and not title:
                    title = stripped[2:].strip()
                if "**Source URL:**" in stripped and not url:
                    url = stripped.replace("**Source URL:**", "").strip()
                if "**Query:**" in stripped and not title:
                    title = "Search: " + stripped.replace("**Query:**", "").strip()
            articles.append({
                "title":  title or path.stem,
                "url":    url,
                "folder": path.stem,
                "text":   text,
            })
        except Exception:
            continue
    return articles


# ====================================================================================================
# MARK: ANALYSIS PROMPT BUILDER
# ====================================================================================================
def _build_analysis_prompt(domain: str, when: _date, topic: str, articles: list[dict]) -> str:
    date_str   = when.strftime("%Y-%m-%d")
    topic_line = f"Topic focus: {topic.strip()}\n\n" if topic.strip() else ""

    header = (
        f"You are an expert research analyst producing a daily intelligence briefing.\n"
        f"Below are {len(articles)} document(s) collected on {date_str} in the "
        f"research domain \"{domain}\".\n"
        f"{topic_line}"
        f"Produce a structured daily research report in Markdown with exactly these "
        f"four sections:\n\n"
        f"## Executive Summary\n"
        f"3 to 5 bullet-point takeaways covering the most important findings.\n\n"
        f"## Main Stories\n"
        f"One subsection (### heading) per distinct story or theme found across "
        f"the documents. 3–5 sentences per subsection. End each with a "
        f"**Source:** line giving the article or search title.\n\n"
        f"## Notable Data Points\n"
        f"Bullet list of specific figures, product names, dates, or direct quotes "
        f"worth noting.\n\n"
        f"## Overall Assessment\n"
        f"2–3 sentences summarising the day's landscape and any notable trends.\n\n"
        f"Do NOT add any preamble, greeting, or commentary outside these four "
        f"sections. Output only valid Markdown.\n\n"
        f"---\n\n"
    )

    article_blocks: list[str] = []
    for i, a in enumerate(articles, 1):
        lines = [f"## Document {i}: {a['title']}"]
        if a["url"]:
            lines.append(f"URL: {a['url']}")
        lines.append("")
        lines.append(a["text"])
        lines.append("\n---\n")
        article_blocks.append("\n".join(lines))

    return header + "\n\n".join(article_blocks)


# ====================================================================================================
# MARK: MODEL RESOLUTION
# ====================================================================================================
def _safe_resolve_model(model_alias: str) -> str:
    """Resolve a short model alias (e.g. "120b") to a full installed model name.

    Falls back to the original string if Ollama is unreachable or the alias is unresolvable.
    """
    try:
        available = list_ollama_models()
        resolved  = resolve_model_name(model_alias, available)
        return resolved or model_alias
    except Exception:
        return model_alias


# ====================================================================================================
# MARK: ANALYSIS FILE LOCATOR
# ====================================================================================================
def _find_analysis_file(domain: str, when: _date) -> Path | None:
    """Return analysis.md under 02-Analysis/<domain>/yyyy/mm/dd/, or None."""
    path = get_date_dir(STAGE_ANALYSIS, domain, when) / "analysis.md"
    return path if path.exists() else None


# ====================================================================================================
# MARK: DATE DIRECTORY ITERATOR (shared by list_mine_days and list_analyses)
# ====================================================================================================
def _iter_date_dirs(stage: str, domain: str, max_days: int) -> list[tuple[_date, Path]]:
    """Walk a domain's yyyy/mm/dd directory tree newest-first, up to max_days entries."""
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
def create_daily_summary(
    domain: str,
    date: str = "",
    topic: str = "",
    model: str = _DEFAULT_MODEL,
    num_ctx: int = _DEFAULT_NUM_CTX,
) -> str:
    """Read all mined content for a domain+date, call the LLM to produce a structured
    intelligence briefing, and save it to the 02-Analysis stage.

    Parameters
    ----------
    domain  : research domain label (must match what was used when mining)
    date    : YYYY-MM-DD, "today", "yesterday", or "" (defaults to today)
    topic   : optional context hint for the analyst (e.g. "AI hardware releases")
    model   : Ollama model alias or name, default "20b"
    num_ctx : LLM context window in tokens, default 131072

    Returns "Saved: <path>  (N articles, N words)" on success.
    Returns a descriptive "Error: ..." string on failure - never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        when = _parse_date(date)
    except ValueError:
        return f"Error: invalid date {date!r}. Use YYYY-MM-DD, 'today', or 'yesterday'."

    content_files = _find_content_files(domain.strip(), when)
    if not content_files:
        date_label = when.strftime("%Y/%m/%d")
        return f"No mined content found in 01-Mine/{domain}/{date_label}/"

    articles = _read_articles(content_files)
    if not articles:
        return "Error: could not read any article content."

    prompt   = _build_analysis_prompt(domain.strip(), when, topic, articles)
    resolved = _safe_resolve_model(str(model))

    prompt_words = len(prompt.split())
    print(f"[Analysis] {len(articles)} document(s), ~{prompt_words:,} words in prompt (~{int(prompt_words * 1.3):,} tokens est.), ctx={int(num_ctx):,}")

    try:
        result         = call_ollama_extended(model_name=resolved, prompt=prompt, num_ctx=int(num_ctx))
        analysis_body  = result.response.strip()
    except Exception as exc:
        return f"Error: LLM call failed: {exc}"

    if not analysis_body:
        return "Error: LLM returned an empty response."

    # Build the full saved document - structured header + LLM-generated body
    now    = _datetime.now().strftime("%Y-%m-%d %H:%M")
    header = "\n".join([
        f"# Daily Research Summary: {domain} - {when.strftime('%Y-%m-%d')}",
        "",
        f"**Generated:** {now}",
        f"**Documents analysed:** {len(articles)}",
        f"**Model:** {resolved}",
    ])
    if topic.strip():
        header += f"\n**Topic context:** {topic.strip()}"
    header += "\n\n---\n"

    full_document = header + "\n" + analysis_body

    try:
        date_dir    = ensure_date_dir(STAGE_ANALYSIS, domain.strip(), when)
        output_path = date_dir / "analysis.md"
        output_path.write_text(full_document, encoding="utf-8")
    except Exception as exc:
        return f"Error: failed to save analysis: {exc}"

    word_count = len(analysis_body.split())
    tps_str    = f", {result.tokens_per_second:.1f} tok/s" if result.tokens_per_second > 0 else ""
    return (
        f"Saved: {output_path}\n"
        f"  ({len(articles)} document(s) analysed, {word_count} words written{tps_str})"
    )


# ----------------------------------------------------------------------------------------------------
def list_mine_days(domain: str, max_days: int = 7) -> str:
    """List available mined date directories for a domain, newest first.

    Useful for the planner to discover which dates have content ready for analysis.

    Returns a formatted multi-line string, or an error string.  Never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        entries = _iter_date_dirs(STAGE_MINE, domain.strip(), max(1, int(max_days)))
    except Exception as exc:
        return f"Error: {exc}"

    if not entries:
        return f"No mined content found for domain '{domain}'."

    lines = [f"Mined content available for domain '{domain}':"]
    for d, day_dir in entries:
        file_count = len(list(day_dir.glob("*.md")))
        lines.append(f"  {d.strftime('%Y-%m-%d')}:  {file_count} mined file(s)")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def list_analyses(domain: str, max_days: int = 7) -> str:
    """List completed analysis files for a domain, newest first.

    Returns a formatted multi-line string, or an error string.  Never raises.
    """
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    try:
        entries = _iter_date_dirs(STAGE_ANALYSIS, domain.strip(), max(1, int(max_days)))
    except Exception as exc:
        return f"Error: {exc}"

    if not entries:
        return f"No completed analyses found for domain '{domain}'."

    lines = [f"Completed analyses for domain '{domain}':"]
    for d, day_dir in entries:
        exists = (day_dir / "analysis.md").exists()
        lines.append(f"  {d.strftime('%Y-%m-%d')}:  {'1 analysis file' if exists else 'no analysis file'}")
    return "\n".join(lines)
