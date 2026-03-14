# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Validates a single orchestration iteration before accepting its result.
#
# Called after each planner/executor/LLM cycle in orchestration.py. Returns a ValidationResult
# describing whether the iteration passed, a step-by-step check trace for detailed logging, and
# structured planner feedback for the retry prompt when validation fails.
#
# Checks performed (in order):
#   1. The planner returned at least one python_call.
#   2. At least one skill call was actually executed.
#   3. No call result looks like a skill-level failure.
#   4. No unresolved {{ }} template placeholders remain in the final prompt.
#   5. The LLM produced a non-empty final response.
#   6. Multi-skill chains reference earlier outputs via placeholder syntax.
#
# Related modules:
#   - orchestration.py  -- calls validate_orchestration_iteration inside the retry loop
#   - planner_engine.py -- provides the ExecutionPlan type consumed here
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from dataclasses import dataclass, field

from planner_engine import ExecutionPlan


# Matches placeholder tokens that the skill executor will actually resolve.
_CHAIN_PLACEHOLDER_RE = re.compile(
    r"\{\{output_of_(?:first|previous|\w+)_call\}\}"
    r"|\{\{output\d+\}\}"
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


# ====================================================================================================
# MARK: RESULT
# ====================================================================================================
@dataclass
class ValidationResult:
    """Outcome of a single orchestration iteration's validation pass.

    Attributes:
        passed               -- True when all checks succeed.
        message              -- One-line summary (pass or first failure description).
        checks_log           -- Ordered list of per-check trace lines; logged verbatim by
                                orchestration.py so each step is visible in the session log.
        planner_feedback     -- Structured feedback string suitable for injection into the
                                retry planner prompt; richer and more targeted than `message`.
        failed_check         -- Machine-readable tag for which check failed, or "" on pass.
                                Values: "no_calls" | "no_executions" | "call_failed" |
                                        "unresolved_placeholders" | "empty_response" |
                                        "no_chain_placeholders"
        failed_call_order    -- call.order value of the failing skill call, or None.
        failed_call_function -- function name of the failing skill call, or None.
        failed_result        -- Raw result string from the failing call, or None.
    """
    passed:               bool
    message:              str
    checks_log:           list[str]
    planner_feedback:     str
    failed_check:         str        = ""
    failed_call_order:    int | None = None
    failed_call_function: str | None = None
    failed_result:        str | None = None


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _python_call_failed(call_output: dict) -> tuple[bool, str]:
    result = call_output.get("result")
    if not isinstance(result, str):
        return False, ""

    normalized = result.strip().lower()
    if normalized.startswith(_RESULT_FAILURE_PREFIXES):
        return True, result.strip()

    return False, ""


def _pass(checks: list[str], message: str) -> None:
    checks.append(f"[PASS] {message}")


def _fail(checks: list[str], message: str) -> None:
    checks.append(f"[FAIL] {message}")


# ====================================================================================================
# MARK: VALIDATION
# ====================================================================================================
def validate_orchestration_iteration(
    plan: ExecutionPlan,
    python_call_outputs: list[dict],
    final_prompt: str,
    final_response: str,
) -> ValidationResult:
    checks: list[str] = []

    # -- Check 1: plan has calls ------------------------------------------------------------------
    if not plan.python_calls:
        _fail(checks, "Plan has no python_calls.")
        msg = "Planner returned no python_calls."
        return ValidationResult(
            passed=False, message=msg, checks_log=checks,
            planner_feedback=(
                f"[VALIDATION FAIL - no_calls] {msg} "
                f"Produce a plan with at least one valid function call."
            ),
            failed_check="no_calls",
        )
    _pass(checks, f"Plan contains {len(plan.python_calls)} python_call(s).")

    # -- Check 2: calls were executed -------------------------------------------------------------
    if not python_call_outputs:
        _fail(checks, "No skill calls were executed (outputs list is empty).")
        msg = "No python calls executed."
        return ValidationResult(
            passed=False, message=msg, checks_log=checks,
            planner_feedback=(
                f"[VALIDATION FAIL - no_executions] {msg} "
                f"Check that module paths and function names exactly match the skills catalog."
            ),
            failed_check="no_executions",
        )
    _pass(checks, f"{len(python_call_outputs)} skill call(s) executed.")

    # -- Check 3: call results are not skill-level failures ---------------------------------------
    for call_output in python_call_outputs:
        call_failed, failure_text = _python_call_failed(call_output)
        order   = call_output.get("order")
        fn_name = call_output.get("function", "?")
        if call_failed:
            _fail(checks, f"Call {order} ({fn_name}) returned a failure: {failure_text[:120]}")
            msg = f"Python call {order} ({fn_name}) failed: {failure_text}"
            return ValidationResult(
                passed=False, message=msg, checks_log=checks,
                planner_feedback=(
                    f"[VALIDATION FAIL - call_failed] Call {order} ({fn_name}) returned: "
                    f"'{failure_text[:200]}'. "
                    f"Revise or remove that call - check argument values and types."
                ),
                failed_check="call_failed",
                failed_call_order=order,
                failed_call_function=fn_name,
                failed_result=failure_text,
            )
        _pass(checks, f"Call {order} ({fn_name}) - result OK.")

    # -- Check 4: no unresolved placeholders in final prompt --------------------------------------
    if "{{" in final_prompt or "}}" in final_prompt:
        _fail(checks, "Final prompt still contains unresolved {{ }} template placeholders.")
        msg = "Final prompt still contains unresolved template placeholders."
        return ValidationResult(
            passed=False, message=msg, checks_log=checks,
            planner_feedback=(
                f"[VALIDATION FAIL - unresolved_placeholders] {msg} "
                f"Ensure every {{{{outputN}}}} or {{{{output_of_*_call}}}} token is satisfied "
                f"by a preceding skill call result."
            ),
            failed_check="unresolved_placeholders",
        )
    _pass(checks, "No unresolved {{ }} placeholders in final prompt.")

    # -- Check 5: LLM response is non-empty -------------------------------------------------------
    if not final_response.strip():
        _fail(checks, "Final LLM response is empty.")
        msg = "Final LLM response was empty."
        return ValidationResult(
            passed=False, message=msg, checks_log=checks,
            planner_feedback=(
                f"[VALIDATION FAIL - empty_response] {msg} "
                f"Simplify the final_prompt_template so the LLM can produce a concrete answer."
            ),
            failed_check="empty_response",
        )
    _pass(checks, f"Final LLM response is non-empty ({len(final_response.strip())} chars).")

    # -- Check 6: multi-skill chains use placeholder syntax ---------------------------------------
    if len(plan.python_calls) > 1:
        min_order        = min(call.order for call in plan.python_calls)
        downstream_calls = [call for call in plan.python_calls if call.order > min_order]
        any_uses_placeholder = (
            any(
                any(_CHAIN_PLACEHOLDER_RE.search(str(v)) for v in call.arguments.values())
                for call in downstream_calls
            )
            or _CHAIN_PLACEHOLDER_RE.search(plan.final_prompt_template or "")
        )
        if not any_uses_placeholder:
            _fail(checks, "Multi-skill plan has no placeholder references in downstream calls.")
            msg = (
                "Multi-skill plan has chained calls but no argument placeholder references. "
                "Use ${output1}, ${output1.field}, ${output2.field} etc. "
                "to pipe outputs from earlier skill calls into later call arguments."
            )
            return ValidationResult(
                passed=False, message=msg, checks_log=checks,
                planner_feedback=(
                    f"[VALIDATION FAIL - no_chain_placeholders] The plan has "
                    f"{len(plan.python_calls)} calls but downstream calls do not reference "
                    f"earlier outputs. Use ${{output1}} (full object), ${{output1.fieldname}} "
                    f"(named field), or ${{output2.fieldname}} for results of later calls."
                ),
                failed_check="no_chain_placeholders",
            )
        _pass(checks, f"Multi-skill chain uses placeholder syntax across {len(downstream_calls)} downstream call(s).")

    _pass(checks, "All validation checks passed.")
    return ValidationResult(
        passed=True,
        message="Validation passed.",
        checks_log=checks,
        planner_feedback="",
    )
