# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Executes individual Python skill calls requested by the LLM tool-calling pipeline.
#
# Loads skill modules dynamically at runtime using importlib, but only after verifying each call
# against an allow-list derived from the skills_summary catalog. This two-step guard - allow-list
# check then dynamic import - prevents arbitrary code execution if a malformed or adversarial tool
# call is received from the LLM.
#
# Also resolves {{token}} placeholders in string arguments before each function call.
#
# Related modules:
#   - orchestration.py           -- calls execute_tool_call inside the tool-calling loop
#   - skills_catalog_builder.py  -- produces the skills_summary that drives the allow-list
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import importlib.util
import re
from pathlib import Path

from prompt_tokens import resolve_tokens
from workspace_utils import get_workspace_root
from workspace_utils import normalize_module_path


# ====================================================================================================
# MARK: MODULE LOADER
# ====================================================================================================
# Cache of already-loaded callables: (absolute_path_str, function_name) -> callable.
# Avoids re-executing module-level code on every skill invocation within a session.
_callable_cache: dict[tuple[str, str], object] = {}


# ----------------------------------------------------------------------------------------------------
def _load_callable_from_module_path(module_path: str, function_name: str):
    workspace_root        = get_workspace_root()

    candidate_module_path = str(module_path).strip()
    if not candidate_module_path.endswith(".py"):
        candidate_module_path = f"{candidate_module_path}.py"

    absolute_module_path  = (workspace_root / candidate_module_path).resolve()

    if not absolute_module_path.exists():
        raise RuntimeError(f"Module path does not exist: {module_path}")

    cache_key = (str(absolute_module_path), function_name)
    if cache_key in _callable_cache:
        return _callable_cache[cache_key]

    # Generate a unique module name to avoid collisions when the same path is loaded multiple times.
    dynamic_module_name = f"skill_module_{absolute_module_path.stem}_{abs(hash(str(absolute_module_path)))}"
    spec                = importlib.util.spec_from_file_location(dynamic_module_name, absolute_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise RuntimeError(f"Function '{function_name}' not found in module '{module_path}'")

    fn = getattr(module, function_name)
    _callable_cache[cache_key] = fn
    return fn


# ----------------------------------------------------------------------------------------------------
def _build_allowlist(skills_payload: dict) -> set[tuple[str, str]]:
    allowlist = set()
    for skill in skills_payload.get("skills", []):
        module = normalize_module_path(skill.get("module", ""))
        for function_name in skill.get("functions", []):
            normalized = str(function_name).split("(")[0].strip()
            if module and normalized:
                allowlist.add((module, normalized))
    return allowlist


# ----------------------------------------------------------------------------------------------------
def _build_function_to_module_index(skills_payload: dict) -> dict[str, str]:
    """Map clean function names to full normalised module paths.

    First occurrence per function name wins (avoids ambiguity when the same function
    name appears across multiple skills).
    """
    index: dict[str, str] = {}
    for skill in skills_payload.get("skills", []):
        module = normalize_module_path(skill.get("module", ""))
        if not module:
            continue
        for func_sig in skill.get("functions", []):
            fname = str(func_sig).split("(")[0].strip()
            if fname and fname not in index:
                index[fname] = module
    return index



# ====================================================================================================
# MARK: EXECUTION
# ====================================================================================================
def execute_tool_call(
    function_name: str,
    arguments: dict,
    skills_payload: dict,
    user_prompt: str = "",
) -> dict:
    """Execute one tool call and return the output record.

    The returned dict has keys: 'function', 'module', 'arguments', 'result'.
    Raises RuntimeError when the function is not allow-listed or cannot be loaded.
    """
    allowlist = _build_allowlist(skills_payload)
    fn_index  = _build_function_to_module_index(skills_payload)

    module_path = fn_index.get(function_name)
    if module_path is None:
        raise RuntimeError(f"Tool '{function_name}' not found in skills catalog")

    if (module_path, function_name) not in allowlist:
        raise RuntimeError(f"Tool '{function_name}' is not allow-listed by skills catalog")

    # Resolve any {{token}} placeholders in string arguments (e.g. {{today}}).
    resolved_args = {
        k: (resolve_tokens(v) if isinstance(v, str) else v)
        for k, v in arguments.items()
    }

    fn     = _load_callable_from_module_path(module_path, function_name)
    result = fn(**resolved_args)

    return {
        "function":  function_name,
        "module":    module_path,
        "arguments": resolved_args,
        "result":    result,
    }
