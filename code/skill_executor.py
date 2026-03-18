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
import sys

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

    # Generate a stable canonical module name so that if slash_commands.py (or any other
    # importer) has already loaded this file via the normal import system, both references
    # share the same module object and module-level state (e.g. _sandbox_enabled).
    dynamic_module_name = f"skill_module_{absolute_module_path.stem}_{abs(hash(str(absolute_module_path)))}"

    # Re-use an already-registered module rather than exec_module-ing a second copy.
    if dynamic_module_name in sys.modules:
        module = sys.modules[dynamic_module_name]
    else:
        spec   = importlib.util.spec_from_file_location(dynamic_module_name, absolute_module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module spec for: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[dynamic_module_name] = module
        spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise RuntimeError(f"Function '{function_name}' not found in module '{module_path}'")

    fn = getattr(module, function_name)
    _callable_cache[cache_key] = fn
    return fn


# ----------------------------------------------------------------------------------------------------
def _build_allowlist(skills_payload: dict) -> set[tuple[str, str, str]]:
    allowlist = set()
    for skill in skills_payload.get("skills", []):
        module = normalize_module_path(skill.get("module", ""))
        planner_tools = skill.get("planner_tools", [])
        if planner_tools:
            for planner_tool in planner_tools:
                tool_name = str(planner_tool.get("name", "")).strip()
                function_name = str(planner_tool.get("function", "")).strip()
                if module and tool_name and function_name:
                    allowlist.add((tool_name, module, function_name))
            continue

        for function_sig in skill.get("functions", []):
            function_name = str(function_sig).split("(")[0].strip()
            if module and function_name:
                allowlist.add((function_name, module, function_name))
    return allowlist


# ----------------------------------------------------------------------------------------------------
def _build_tool_index(skills_payload: dict) -> dict[str, tuple[str, str]]:
    """Map planner tool names to (module_path, function_name)."""
    index: dict[str, tuple[str, str]] = {}
    for skill in skills_payload.get("skills", []):
        module = normalize_module_path(skill.get("module", ""))
        if not module:
            continue
        planner_tools = skill.get("planner_tools", [])
        if planner_tools:
            for planner_tool in planner_tools:
                tool_name = str(planner_tool.get("name", "")).strip()
                function_name = str(planner_tool.get("function", "")).strip()
                if tool_name and function_name:
                    index[tool_name] = (module, function_name)
            continue

        for function_sig in skill.get("functions", []):
            function_name = str(function_sig).split("(")[0].strip()
            if function_name:
                index[function_name] = (module, function_name)
    return index



# ====================================================================================================
# MARK: EXECUTION
# ====================================================================================================
def execute_tool_call(
    tool_name: str,
    arguments: dict,
    skills_payload: dict,
    user_prompt: str = "",
) -> dict:
    """Execute one tool call and return the output record.

    The returned dict has keys: 'function', 'module', 'arguments', 'result'.
    Raises RuntimeError when the function is not allow-listed or cannot be loaded.
    """
    allowlist = _build_allowlist(skills_payload)
    tool_index = _build_tool_index(skills_payload)

    resolved = tool_index.get(tool_name)
    if resolved is None:
        raise RuntimeError(f"Tool '{tool_name}' not found in skills catalog")
    module_path, function_name = resolved

    if (tool_name, module_path, function_name) not in allowlist:
        raise RuntimeError(f"Tool '{tool_name}' is not allow-listed by skills catalog")

    # Resolve any {{token}} placeholders in string arguments (e.g. {{today}}).
    resolved_args = {
        k: (resolve_tokens(v) if isinstance(v, str) else v)
        for k, v in arguments.items()
    }

    fn     = _load_callable_from_module_path(module_path, function_name)
    result = fn(**resolved_args)

    return {
        "tool":      tool_name,
        "function":  function_name,
        "module":    module_path,
        "arguments": resolved_args,
        "result":    result,
    }
