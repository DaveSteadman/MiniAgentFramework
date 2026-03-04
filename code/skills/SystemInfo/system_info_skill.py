# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# SystemInfo skill module for the MiniAgentFramework.
#
# Provides two callable functions that the orchestration planner can select when a user prompt
# requires information about the runtime environment:
#   - get_system_info_string()         -- returns Python and Ollama version strings.
#   - build_prompt_with_system_info()  -- returns the system info string to use as prompt context.
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
import re
import subprocess
import sys


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _get_python_version() -> str:
    return sys.version.split()[0]


# ----------------------------------------------------------------------------------------------------
def _get_ollama_version() -> str:
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
        raw_output = f"{result.stdout} {result.stderr}".strip()
        if result.returncode != 0:
            return "unknown"

        match = re.search(r"(\d+\.\d+\.\d+)", raw_output)
        if match:
            return match.group(1)

        return raw_output or "unknown"
    except Exception:
        return "unknown"


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def get_system_info_string() -> str:
    python_version = _get_python_version()
    ollama_version = _get_ollama_version()
    return f"System info: python={python_version}; ollama={ollama_version}"


# ----------------------------------------------------------------------------------------------------
def build_prompt_with_system_info(prompt: str) -> str:
    return get_system_info_string()
