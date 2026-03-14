# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Shared workspace-root resolution and well-known directory accessors for the MiniAgentFramework.
#
# All modules that need to construct paths relative to the repository root should import
# the relevant accessor from here rather than rolling their own __file__-based computation.
# This ensures a single definition that is resilient to internal directory reorganisation
# and eliminates the three divergent implementations that previously existed in:
#   - skill_executor.py          (parent.parent)
#   - file_access_skill.py       (parents[3])
#
# Well-known directory accessors (all cached):
#   get_workspace_root()      ->  <repo_root>/
#   get_controldata_dir()     ->  <repo_root>/controldata/
#   get_logs_dir()            ->  <repo_root>/controldata/logs/
#   get_schedules_dir()       ->  <repo_root>/controldata/schedules/
#   get_test_prompts_dir()    ->  <repo_root>/controldata/test_prompts/
#   get_test_results_dir()    ->  <repo_root>/controldata/test_results/
#   get_chatsessions_dir()    ->  <repo_root>/controldata/chatsessions/
#
# Related modules:
#   - file_access_skill.py  -- uses get_workspace_root() for path-safety checks
#   - skill_executor.py     -- uses get_workspace_root() to resolve skill module paths
#   - main.py               -- uses get_logs_dir(), get_schedules_dir()
#   - testcode/test_wrapper.py -- uses get_test_results_dir(), get_test_prompts_dir()
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from functools import lru_cache
from pathlib import Path


# ====================================================================================================
# MARK: ROOT RESOLUTION
# ====================================================================================================
@lru_cache(maxsize=1)
def get_workspace_root() -> Path:
    """Return the absolute path to the repository root (the directory containing the code/ folder).

    Cached after first call so repeated lookups cost nothing - the root cannot change within
    a single process lifetime.
    """
    # This file lives at <repo_root>/code/workspace_utils.py
    return Path(__file__).resolve().parent.parent


# ====================================================================================================
# MARK: CONTROLDATA DIRECTORY ACCESSORS
# ====================================================================================================
@lru_cache(maxsize=1)
def get_controldata_dir() -> Path:
    """Return the absolute path to the controldata/ directory."""
    return get_workspace_root() / "controldata"


@lru_cache(maxsize=1)
def get_logs_dir() -> Path:
    """Return the absolute path to the controldata/logs/ directory."""
    return get_controldata_dir() / "logs"


@lru_cache(maxsize=1)
def get_schedules_dir() -> Path:
    """Return the absolute path to the controldata/schedules/ directory."""
    return get_controldata_dir() / "schedules"


@lru_cache(maxsize=1)
def get_test_prompts_dir() -> Path:
    """Return the absolute path to the controldata/test_prompts/ directory."""
    return get_controldata_dir() / "test_prompts"


@lru_cache(maxsize=1)
def get_test_results_dir() -> Path:
    """Return the absolute path to the controldata/test_results/ directory."""
    return get_controldata_dir() / "test_results"


@lru_cache(maxsize=1)
def get_chatsessions_dir() -> Path:
    """Return the absolute path to the controldata/chatsessions/ directory."""
    return get_controldata_dir() / "chatsessions"


# ====================================================================================================
# MARK: PATH UTILITIES
# ====================================================================================================
def normalize_module_path(module_path: str) -> str:
    """Normalise a skill module path to a canonical form for allow-list comparisons.

    Strips leading ./ prefixes and any trailing .py extension so paths from different
    sources (skills_summary catalog vs LLM planner output) compare equal.
    """
    normalized = str(module_path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized
