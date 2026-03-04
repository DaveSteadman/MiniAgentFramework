# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# DateTime skill module for the MiniAgentFramework.
#
# Provides two callable functions that the orchestration planner can select when a user prompt
# requires the current date or time:
#   - get_datetime_string()          -- returns the current local date/time as a formatted string.
#   - build_prompt_with_datetime()   -- prepends the date/time string to an arbitrary prompt.
#
# This module is discovered automatically by skills_catalog_builder.py via the accompanying
# skill.md definition file and added to the skills_summary.md catalog.
#
# Related modules:
#   - skill_executor.py         -- dynamically imports and calls functions from this module
#   - skills_catalog_builder.py -- reads skill.md to build the catalog entry for this skill
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from datetime import datetime


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def get_datetime_string() -> str:
    current_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Current date/time: {current_local}"


# ----------------------------------------------------------------------------------------------------
def build_prompt_with_datetime(prompt: str) -> str:
    datetime_prefix = get_datetime_string()
    return f"{datetime_prefix}\n{prompt}"
