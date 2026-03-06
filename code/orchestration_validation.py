# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Validates a single orchestration iteration before accepting its result.
#
# Called after each planner/executor/LLM cycle in main.py. If validation fails the orchestration
# loop feeds the returned message back to the planner as corrective feedback and retries.
#
# Checks performed:
#   - The planner returned at least one python_call.
#   - At least one skill call was actually executed.
#   - No unresolved {{ }} template placeholders remain in the final prompt.
#   - The LLM produced a non-empty final response.
#
# Related modules:
#   - main.py           -- calls validate_orchestration_iteration inside the retry loop
#   - planner_engine.py -- provides the ExecutionPlan type consumed here
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re

from planner_engine import ExecutionPlan


# Matches placeholder tokens that the skill executor will actually resolve.
_CHAIN_PLACEHOLDER_RE = re.compile(
    r"\{\{output_of_(?:first|previous)_call\}\}"
    r"|\$\{output\d+(?:\.[A-Za-z_][A-Za-z0-9_]*)*\}"
    r"|\{\d+\}(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
_RESULT_FAILURE_PREFIXES = (
    "error:",
    "no file path found",
    "unable to parse",
    "instruction not recognized",
    "file not found:",
    "path escapes workspace root",
    "execution failed",
)


# ----------------------------------------------------------------------------------------------------
def _python_call_failed(call_output: dict) -> tuple[bool, str]:
    result = call_output.get("result")
    if not isinstance(result, str):
        return False, ""

    normalized = result.strip().lower()
    if normalized.startswith(_RESULT_FAILURE_PREFIXES):
        return True, result.strip()

    return False, ""


# ====================================================================================================
# MARK: VALIDATION
# ====================================================================================================
def validate_orchestration_iteration(
    plan: ExecutionPlan,
    python_call_outputs: list[dict],
    final_prompt: str,
    final_response: str,
) -> tuple[bool, str]:
    if not plan.python_calls:
        return False, "Planner returned no python_calls."

    if not python_call_outputs:
        return False, "No python calls executed."

    for call_output in python_call_outputs:
        call_failed, failure_text = _python_call_failed(call_output)
        if call_failed:
            return False, (
                f"Python call {call_output.get('order')} ({call_output.get('function')}) failed: "
                f"{failure_text}"
            )

    # Detect double-brace placeholders that were never substituted by skill outputs.
    if "{{" in final_prompt or "}}" in final_prompt:
        return False, "Final prompt still contains unresolved template placeholders."

    if not final_response.strip():
        return False, "Final LLM response was empty."

    # For multi-skill chains, verify the planner used actual placeholder syntax to chain outputs.
    # This catches the failure mode where the LLM writes a literal like 'time_placeholder'
    # instead of {{output_of_previous_call}} or ${output1.time}.
    if len(plan.python_calls) > 1:
        min_order = min(call.order for call in plan.python_calls)
        downstream_calls = [call for call in plan.python_calls if call.order > min_order]
        any_uses_placeholder = any(
            any(_CHAIN_PLACEHOLDER_RE.search(str(v)) for v in call.arguments.values())
            for call in downstream_calls
        )
        if not any_uses_placeholder:
            return False, (
                "Multi-skill plan has chained calls but no argument placeholder references. "
                "Use {{output_of_previous_call}}, {{output_of_first_call}}, or ${output1.key} "
                "to pipe outputs from earlier skill calls into later call arguments."
            )

    return True, "Validation passed."
