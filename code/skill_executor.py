# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import importlib.util
from pathlib import Path

from planner_engine import ExecutionPlan
from planner_engine import PythonCall


# ====================================================================================================
# MARK: EXECUTION TYPES
# ====================================================================================================
class ExecutedCall(dict):
    pass


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _resolve_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------------------------------
def _load_callable_from_module_path(module_path: str, function_name: str):
    workspace_root        = _resolve_workspace_root()
    absolute_module_path  = (workspace_root / module_path).resolve()

    if not absolute_module_path.exists():
        raise RuntimeError(f"Module path does not exist: {module_path}")

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
        module = str(skill.get("module", "")).strip()
        for function_name in skill.get("functions", []):
            normalized = str(function_name).split("(")[0].strip()
            if module and normalized:
                allowlist.add((module, normalized))
    return allowlist


# ----------------------------------------------------------------------------------------------------
def _validate_call_allowed(call: PythonCall, allowlist: set[tuple[str, str]]) -> None:
    key = (call.module, call.function)
    if key not in allowlist:
        raise RuntimeError(f"Planned call is not allow-listed by skills summary: {call.module}.{call.function}")


# ----------------------------------------------------------------------------------------------------
def _resolve_argument_placeholders(call_arguments: dict, previous_outputs: list[str], user_prompt: str) -> dict:
    resolved = {}

    for key, value in call_arguments.items():
        if not isinstance(value, str):
            resolved[key] = value
            continue

        normalized = value.strip()
        if normalized == "{{user_prompt}}":
            resolved[key] = user_prompt
            continue

        if normalized == "{{output_of_first_call}}" and len(previous_outputs) >= 1:
            resolved[key] = previous_outputs[0]
            continue

        if normalized == "{{output_of_previous_call}}" and previous_outputs:
            resolved[key] = previous_outputs[-1]
            continue

        resolved[key] = value

    return resolved


# ====================================================================================================
# MARK: EXECUTION
# ====================================================================================================
def execute_skill_plan_calls(plan: ExecutionPlan, user_prompt: str, skills_payload: dict) -> tuple[list[dict], str]:
    allowlist     = _build_allowlist(skills_payload=skills_payload)
    call_outputs  = []
    raw_outputs   = []
    latest_output = user_prompt

    for call in sorted(plan.python_calls, key=lambda item: item.order):
        # One-line comment: Enforce strict allow-list from skills_summary before any dynamic import execution.
        _validate_call_allowed(call=call, allowlist=allowlist)

        call_arguments = _resolve_argument_placeholders(
            call_arguments=dict(call.arguments),
            previous_outputs=raw_outputs,
            user_prompt=user_prompt,
        )

        # One-line comment: Dynamically import the approved skill module and invoke the selected function.
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
        raw_outputs.append(str(result))
        latest_output = str(result)

    return call_outputs, latest_output
