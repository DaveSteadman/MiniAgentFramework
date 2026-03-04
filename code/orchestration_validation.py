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
from planner_engine import ExecutionPlan


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

    # Detect double-brace placeholders that were never substituted by skill outputs.
    if "{{" in final_prompt or "}}" in final_prompt:
        return False, "Final prompt still contains unresolved template placeholders."

    if not final_response.strip():
        return False, "Final LLM response was empty."

    return True, "Validation passed."
