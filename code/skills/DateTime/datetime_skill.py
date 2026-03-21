# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# DateTime skill module for the MiniAgentFramework.
#
# Provides a single callable function that returns structured date and time values.
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
def get_datetime_data() -> dict:
    current_local = datetime.now()
    return {
        "date": current_local.strftime("%Y-%m-%d"),
        "time": current_local.strftime("%H:%M:%S"),
    }


# ----------------------------------------------------------------------------------------------------
def get_day_name() -> str:
    """Return the full name of the current day of the week, e.g. 'Saturday'."""
    return datetime.now().strftime("%A")


# ----------------------------------------------------------------------------------------------------
def get_month_name() -> str:
    """Return the full name of the current month, e.g. 'March'."""
    return datetime.now().strftime("%B")
