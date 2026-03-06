# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Executes the approved Python skill calls declared in an ExecutionPlan.
#
# Loads skill modules dynamically at runtime using importlib, but only after verifying each call
# against an allow-list derived from the skills_summary catalog. This two-step guard — allow-list
# check then dynamic import — prevents arbitrary code execution if a malformed or adversarial plan
# is received from the LLM planner.
#
# Also resolves template argument placeholders (e.g. {{user_prompt}}, {{output_of_previous_call}})
# before each function call so that skill calls can chain outputs together.
#
# Related modules:
#   - planner_engine.py         -- provides the ExecutionPlan and PythonCall types
#   - main.py                   -- calls execute_skill_plan_calls inside the orchestration loop
#   - skills_catalog_builder.py -- produces the skills_summary that drives the allow-list
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import importlib.util
import logging
import re
from pathlib import Path

from planner_engine import ExecutionPlan
from planner_engine import PythonCall
from workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: EXECUTION TYPES
# ====================================================================================================
class ExecutedCall(dict):
    pass


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _normalize_module_path(module_path: str) -> str:
    # Strip leading ./ prefixes and the .py extension so paths can be compared uniformly.
    normalized = str(module_path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    return normalized


# ----------------------------------------------------------------------------------------------------
def _load_callable_from_module_path(module_path: str, function_name: str):
    workspace_root        = get_workspace_root()

    candidate_module_path = str(module_path).strip()
    if not candidate_module_path.endswith(".py"):
        candidate_module_path = f"{candidate_module_path}.py"

    absolute_module_path  = (workspace_root / candidate_module_path).resolve()

    if not absolute_module_path.exists():
        raise RuntimeError(f"Module path does not exist: {module_path}")

    # Generate a unique module name to avoid collisions when the same path is loaded multiple times.
    dynamic_module_name = f"skill_module_{absolute_module_path.stem}_{abs(hash(str(absolute_module_path)))}"
    spec                = importlib.util.spec_from_file_location(dynamic_module_name, absolute_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise RuntimeError(f"Function '{function_name}' not found in module '{module_path}'")

    return getattr(module, function_name)


# ----------------------------------------------------------------------------------------------------
def _build_allowlist(skills_payload: dict) -> set[tuple[str, str]]:
    allowlist = set()
    for skill in skills_payload.get("skills", []):
        module = _normalize_module_path(skill.get("module", ""))
        for function_name in skill.get("functions", []):
            normalized = str(function_name).split("(")[0].strip()
            if module and normalized:
                allowlist.add((module, normalized))
    return allowlist


# ----------------------------------------------------------------------------------------------------
def _validate_call_allowed(call: PythonCall, allowlist: set[tuple[str, str]]) -> None:
    key = (_normalize_module_path(call.module), call.function)
    if key not in allowlist:
        raise RuntimeError(f"Planned call is not allow-listed by skills summary: {call.module}.{call.function}")


# ----------------------------------------------------------------------------------------------------
def _resolve_indexed_path(index: int, path_segments: list[str], previous_results: list[object]):
    if index < 0 or index >= len(previous_results):
        return None, False

    value = previous_results[index]
    for segment in path_segments:
        if isinstance(value, dict) and segment in value:
            value = value[segment]
            continue
        return None, False

    return value, True


# ----------------------------------------------------------------------------------------------------
def _resolve_structured_reference(reference: str, previous_results: list[object]):
    brace_match = re.match(r"^\{(\d+)\}(?:\.[A-Za-z_][A-Za-z0-9_]*)*$", reference)
    if brace_match:
        index = int(brace_match.group(1))
        path_segments = [segment for segment in reference.split(".")[1:] if segment]
        return _resolve_indexed_path(index=index, path_segments=path_segments, previous_results=previous_results)

    output_match = re.match(r"^\$\{output(\d+)(?:\.[A-Za-z_][A-Za-z0-9_]*)*\}$", reference)
    if output_match:
        raw_index = int(output_match.group(1))
        # `${output1...}` maps to the first prior result; `${output0...}` is also accepted.
        index = raw_index - 1 if raw_index >= 1 else raw_index
        inner = reference[2:-1]
        path_segments = [segment for segment in inner.split(".")[1:] if segment]
        return _resolve_indexed_path(index=index, path_segments=path_segments, previous_results=previous_results)

    return None, False


# ----------------------------------------------------------------------------------------------------
def _resolve_argument_placeholders(call_arguments: dict, previous_results: list[object], user_prompt: str) -> dict:
    resolved = {}

    for key, value in call_arguments.items():
        if not isinstance(value, str):
            resolved[key] = value
            continue

        normalized = value.strip()
        if normalized == "{{user_prompt}}":
            resolved[key] = user_prompt
            continue

        if normalized == "{{output_of_first_call}}" and len(previous_results) >= 1:
            resolved[key] = previous_results[0]
            continue

        if normalized == "{{output_of_previous_call}}" and previous_results:
            resolved[key] = previous_results[-1]
            continue

        structured_value, resolved_structured = _resolve_structured_reference(
            reference=normalized,
            previous_results=previous_results,
        )
        if resolved_structured:
            resolved[key] = structured_value
            continue

        resolved[key] = value

    return resolved


# ====================================================================================================
# MARK: EXECUTION
# ====================================================================================================
def execute_skill_plan_calls(plan: ExecutionPlan, user_prompt: str, skills_payload: dict) -> tuple[list[dict], str]:
    allowlist     = _build_allowlist(skills_payload=skills_payload)
    call_outputs  = []
    raw_results   = []
    latest_output = user_prompt

    for call in sorted(plan.python_calls, key=lambda item: item.order):
        try:
            # Enforce strict allow-list from skills_summary before any dynamic import execution.
            _validate_call_allowed(call=call, allowlist=allowlist)

            call_arguments = _resolve_argument_placeholders(
                call_arguments=dict(call.arguments),
                previous_results=raw_results,
                user_prompt=user_prompt,
            )

            # Dynamically import the approved skill module and invoke the selected function.
            function_ref = _load_callable_from_module_path(module_path=call.module, function_name=call.function)
            result       = function_ref(**call_arguments)

            call_outputs.append(
                {
                    "order": call.order,
                    "module": call.module,
                    "function": call.function,
                    "arguments": call_arguments,
                    "result": result,
                }
            )
            raw_results.append(result)
            latest_output = str(result)

        except Exception as exc:
            logging.exception(
                "Skill call failed (order=%s, module=%s, function=%s); skipping and continuing.",
                call.order,
                call.module,
                call.function,
            )
            call_outputs.append(
                {
                    "order":         call.order,
                    "module":        call.module,
                    "function":      call.function,
                    "error":         True,
                    "error_type":    type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            raw_results.append(None)

    return call_outputs, latest_output
