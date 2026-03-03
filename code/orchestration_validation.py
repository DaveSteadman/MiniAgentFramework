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

    if "{{" in final_prompt or "}}" in final_prompt:
        return False, "Final prompt still contains unresolved template placeholders."

    if not final_response.strip():
        return False, "Final LLM response was empty."

    return True, "Validation passed."
