# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Scratchpad skill module for the MiniAgentFramework.
#
# Thin wrapper that re-exports the four LLM-callable functions from the shared scratchpad
# module (code/scratchpad.py).  Keeping the implementation in scratchpad.py allows
# prompt_tokens.py and orchestration.py to import the same module-level state without
# creating a circular dependency through the skill loader.
#
# Functions exposed to the tool-calling pipeline:
#   scratch_save(key, value)           -- store a named string value
#   scratch_load(key)                  -- retrieve a stored value
#   scratch_list()                     -- list active keys and sizes
#   scratch_delete(key)                -- remove one key
#   scratch_query(key, query, ...)     -- run an isolated LLM call on stored content, returns compact result
#
# Related modules:
#   - code/scratchpad.py                -- owns the module-level _STORE dict and all logic
#   - code/prompt_tokens.py             -- resolves {scratch:key} tokens using get_store()
#   - code/orchestration.py             -- injects active key names into the system prompt
#   - code/skills/Scratchpad/skill.md   -- LLM-facing documentation and examples
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
from pathlib import Path

# Ensure the code/ directory is on the path so that the shared scratchpad module is importable
# when this skill file is loaded dynamically from the workspace root by skill_executor.py.
_code_dir = str(Path(__file__).resolve().parents[2])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

from agent_core.scratchpad import scratch_delete
from agent_core.scratchpad import scratch_dump
from agent_core.scratchpad import scratch_list
from agent_core.scratchpad import scratch_load
from agent_core.scratchpad import scratch_peek
from agent_core.scratchpad import scratch_query
from agent_core.scratchpad import scratch_save
from agent_core.scratchpad import scratch_search


# ====================================================================================================
# MARK: PUBLIC API
# ====================================================================================================
# All four functions are imported directly from code/scratchpad.py and re-exported here so that
# skill_executor._load_callable_from_module_path can resolve them via getattr() on this module.
#
# No additional logic lives here - see code/scratchpad.py for implementation details.
__all__ = [
    "scratch_delete",
    "scratch_dump",
    "scratch_list",
    "scratch_load",
    "scratch_peek",
    "scratch_query",
    "scratch_save",
    "scratch_search",
]
