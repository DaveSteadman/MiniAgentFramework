# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Shared workspace-root resolution for the MiniAgentFramework.
#
# All modules that need to construct paths relative to the repository root should import
# get_workspace_root() from here rather than rolling their own __file__-based computation.
# This ensures a single definition that is resilient to internal directory reorganisation
# and eliminates the three divergent implementations that previously existed in:
#   - skill_executor.py          (parent.parent)
#   - file_access_skill.py       (parents[3])
#
# Related modules:
#   - file_access_skill.py  -- uses get_workspace_root() for path-safety checks
#   - skill_executor.py     -- uses get_workspace_root() to resolve skill module paths
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

    Cached after first call so repeated lookups cost nothing — the root cannot change within
    a single process lifetime.
    """
    # This file lives at <repo_root>/code/workspace_utils.py
    return Path(__file__).resolve().parent.parent
