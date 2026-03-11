# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# System-level token resolution for user prompts and skill arguments.
#
# Provides two utilities used across the framework:
#
#   resolve_tokens(text)       -- replaces {today}, {yesterday}, {month_year}, {month},
#                                 {year}, and {week} in any string with their current values.
#                                 Applied automatically to user prompts in orchestration.py
#                                 and to string skill arguments in skill_executor.py.
#
#   parse_flexible_date(s)     -- converts "today", "yesterday", "YYYY-MM-DD", "YYYY/MM/DD"
#                                 to a date object.  Used by skills whose public API accepts
#                                 a human-readable date parameter.
#
# Tokens are case-insensitive and resolved at call time, so stored/scheduled prompts and
# queries stay perpetually current without manual edits.
#
# Related modules:
#   - orchestration.py              -- calls resolve_tokens on the user prompt
#   - skill_executor.py             -- calls resolve_tokens on string skill arguments
#   - skills/WebMine/...        -- imports resolve_tokens as _resolve_query_tokens
#   - skills/WebResearchAnalysis/.. -- imports parse_flexible_date as _parse_date
#   - skills/WebResearchOutput/...  -- imports parse_flexible_date as _parse_date
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from datetime import date as _date, timedelta as _timedelta


# ====================================================================================================
# MARK: TOKEN RESOLUTION
# ====================================================================================================
_TOKEN_RE = re.compile(
    r"\{(today|yesterday|month_year|month|year|week)\}",
    re.IGNORECASE,
)


def resolve_tokens(text: str) -> str:
    """Replace date/time tokens in a string with their current values.

    Tokens (case-insensitive):
      {today}       -> YYYY-MM-DD          (e.g. 2026-03-08)
      {yesterday}   -> YYYY-MM-DD          (e.g. 2026-03-07)
      {month_year}  -> Month YYYY          (e.g. March 2026)
      {month}       -> full month name     (e.g. March)
      {year}        -> four-digit year     (e.g. 2026)
      {week}        -> ISO week number     (e.g. 10)

    Tokens are resolved at call time so that stored/scheduled prompts and queries
    stay perpetually current without manual edits.
    """
    today     = _date.today()
    yesterday = today - _timedelta(days=1)
    _values   = {
        "today":      today.strftime("%Y-%m-%d"),
        "yesterday":  yesterday.strftime("%Y-%m-%d"),
        "month_year": today.strftime("%B %Y"),
        "month":      today.strftime("%B"),
        "year":       today.strftime("%Y"),
        "week":       today.strftime("%W"),
    }

    def _replace(match: re.Match) -> str:
        return _values[match.group(1).lower()]

    return _TOKEN_RE.sub(_replace, text)


# ====================================================================================================
# MARK: FLEXIBLE DATE PARSING
# ====================================================================================================
def parse_flexible_date(date_str: str) -> _date:
    """Parse a human-readable date string into a date object.

    Accepts:
      ""            -> today
      "today"       -> today
      "yesterday"   -> yesterday
      "YYYY-MM-DD"  -> that date
      "YYYY/MM/DD"  -> that date (normalised to ISO format)

    Raises ValueError for any unrecognised format.
    """
    s = date_str.strip().lower()
    if not s or s == "today":
        return _date.today()
    if s == "yesterday":
        return _date.today() - _timedelta(days=1)
    return _date.fromisoformat(date_str.strip().replace("/", "-"))
