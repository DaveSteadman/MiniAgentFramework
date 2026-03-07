# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Three-stage web research workspace management for MiniAgentFramework.
#
# Manages a structured directory tree for accumulating and progressing web research
# through three clearly separated stages:
#
#   Stage 1 - 01-Mine:          Raw content mined from the web (fetched URLs, search results)
#   Stage 2 - 02-Analysis:      Processed and summarised research artefacts
#   Stage 3 - 03-Presentation:  Final polished outputs for sharing or reporting
#
# Each stage is internally partitioned by:
#   Domain    — a topic label like "GeneralNews" or "CarIndustry"
#   Date      — yyyy/mm/dd nested folders based on when the item was created
#   Sequence  — zero-padded NNN-slug folder inside each date directory
#
# Example directory layout:
#   webresearch/01-Mine/GeneralNews/2026/03/07/001-ev-battery-breakthrough/source.md
#   webresearch/02-Analysis/CarIndustry/2026/03/07/001-ev-market-summary/analysis.md
#   webresearch/03-Presentation/CarIndustry/2026/03/07/001-q1-report/report.md
#
# Well-known stage constants:
#   STAGE_MINE          = "01-Mine"
#   STAGE_ANALYSIS      = "02-Analysis"
#   STAGE_PRESENTATION  = "03-Presentation"
#   ALL_STAGES          = (STAGE_MINE, STAGE_ANALYSIS, STAGE_PRESENTATION)
#
# Path accessors:
#   get_webresearch_root()                          -> <repo_root>/webresearch/
#   get_stage_dir(stage)                            -> webresearch/<stage>/
#   get_domain_dir(stage, domain)                   -> webresearch/<stage>/<domain>/
#   get_date_dir(stage, domain, when=None)          -> webresearch/<stage>/<domain>/yyyy/mm/dd/
#   next_item_number(date_dir)                      -> int  (next NNN sequence number)
#   create_item_dir(stage, domain, slug, when=None) -> Path (creates and returns NNN-slug/)
#
# Related modules:
#   - workspace_utils.py                       -- provides get_workspace_root()
#   - skills/WebResearch/web_research_skill.py -- primary consumer of this module
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from datetime import date as _date
from functools import lru_cache
from pathlib import Path

from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: STAGE CONSTANTS
# ====================================================================================================
STAGE_MINE         = "01-Mine"
STAGE_ANALYSIS     = "02-Analysis"
STAGE_PRESENTATION = "03-Presentation"

ALL_STAGES = (STAGE_MINE, STAGE_ANALYSIS, STAGE_PRESENTATION)

# Regex patterns used for sanitisation and sequence scanning.
_SAFE_DOMAIN_RE  = re.compile(r"[^\w-]")
_SLUG_UNSAFE_RE  = re.compile(r"[^\w-]")
_SLUG_DASH_RE    = re.compile(r"-{2,}")
_SEQ_FOLDER_RE   = re.compile(r"^(\d+)-")


# ====================================================================================================
# MARK: ROOT RESOLUTION
# ====================================================================================================
@lru_cache(maxsize=1)
def get_webresearch_root() -> Path:
    """Return the absolute path to the webresearch/ root directory.

    Cached after first call — the path cannot change within a single process lifetime.
    """
    return get_workspace_root() / "webresearch"


# ====================================================================================================
# MARK: STAGE / DOMAIN / DATE ACCESSORS
# ====================================================================================================
def get_stage_dir(stage: str) -> Path:
    """Return the top-level directory for the given stage.

    Raises ValueError for unrecognised stage names.
    """
    if stage not in ALL_STAGES:
        raise ValueError(f"Unknown stage {stage!r}. Must be one of {ALL_STAGES}.")
    return get_webresearch_root() / stage


# ----------------------------------------------------------------------------------------------------
def _sanitize_domain(domain: str) -> str:
    """Normalise a domain label to a filesystem-safe name.

    Replaces characters that are not alphanumeric, underscores, or hyphens with underscores.
    Leading/trailing whitespace is stripped.
    """
    domain = domain.strip()
    if not domain:
        raise ValueError("domain cannot be empty.")
    return _SAFE_DOMAIN_RE.sub("_", domain)


# ----------------------------------------------------------------------------------------------------
def get_domain_dir(stage: str, domain: str) -> Path:
    """Return the directory for a specific stage + domain combination."""
    return get_stage_dir(stage) / _sanitize_domain(domain)


# ----------------------------------------------------------------------------------------------------
def get_date_dir(stage: str, domain: str, when: _date | None = None) -> Path:
    """Return the yyyy/mm/dd directory for a given stage, domain, and date.

    Defaults to today's date when *when* is not supplied.
    """
    if when is None:
        when = _date.today()
    return get_domain_dir(stage, domain) / when.strftime("%Y") / when.strftime("%m") / when.strftime("%d")


# ====================================================================================================
# MARK: SEQUENCE NUMBERING
# ====================================================================================================
def next_item_number(date_dir: Path) -> int:
    """Return the next available sequence number inside a date directory.

    Scans all NNN-* subdirectories present, finds the highest existing sequence number,
    and returns max + 1.  Returns 1 when the directory is empty or does not yet exist.
    """
    if not date_dir.exists():
        return 1
    max_num = 0
    for child in date_dir.iterdir():
        if child.is_dir():
            match = _SEQ_FOLDER_RE.match(child.name)
            if match:
                max_num = max(max_num, int(match.group(1)))
    return max_num + 1


# ====================================================================================================
# MARK: ITEM DIRECTORY CREATION
# ====================================================================================================
def _make_slug(raw: str, max_length: int = 60) -> str:
    """Produce a clean, hyphen-separated lowercase slug from a raw string."""
    slug = raw.strip().lower()
    slug = _SLUG_UNSAFE_RE.sub("-", slug)
    slug = _SLUG_DASH_RE.sub("-", slug)
    slug = slug.strip("-")[:max_length].rstrip("-")
    return slug or "item"


# ----------------------------------------------------------------------------------------------------
def create_item_dir(
    stage: str,
    domain: str,
    slug: str,
    when: _date | None = None,
) -> Path:
    """Create a new numbered item directory and return its path.

    Directory name format: NNN-slug  (e.g. 001-ev-battery-breakthrough)

    The full directory tree is created if it does not yet exist.
    Thread-safety note: sequence numbering is not atomic; do not call concurrently
    from multiple processes targeting the same date directory.
    """
    date_dir = get_date_dir(stage, domain, when)
    date_dir.mkdir(parents=True, exist_ok=True)

    folder_name = f"{next_item_number(date_dir):03d}-{_make_slug(slug)}"
    item_dir    = date_dir / folder_name
    item_dir.mkdir(exist_ok=True)
    return item_dir
