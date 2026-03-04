# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestration_validation import validate_orchestration_iteration
from planner_engine import ExecutionPlan
from planner_engine import PythonCall
from planner_engine import SelectedSkill


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _make_plan(python_calls: list) -> ExecutionPlan:
    return ExecutionPlan(
        user_prompt="output the time",
        selected_skills=[],
        python_calls=python_calls,
        final_prompt_template="",
    )


def _make_call(order: int = 1) -> PythonCall:
    return PythonCall(
        order=order,
        module="code/skills/DateTime/datetime_skill.py",
        function="get_datetime_string",
        arguments={},
    )


def _make_output(result: str = "Current date/time: 2026-03-04 09:00:00") -> dict:
    return {
        "order": 1,
        "module": "code/skills/DateTime/datetime_skill.py",
        "function": "get_datetime_string",
        "arguments": {},
        "result": result,
    }


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestValidateOrchestrationIteration(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_fails_when_no_python_calls(self):
        plan             = _make_plan(python_calls=[])
        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[_make_output()],
            final_prompt="The current time is 09:00.",
            final_response="It is 9am.",
        )
        self.assertFalse(is_valid)
        self.assertIn("no python_calls", message.lower())

    # ----------------------------------------------------------------------------------------------------
    def test_fails_when_no_python_call_outputs(self):
        plan             = _make_plan(python_calls=[_make_call()])
        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[],
            final_prompt="The current time is 09:00.",
            final_response="It is 9am.",
        )
        self.assertFalse(is_valid)
        self.assertIn("no python calls executed", message.lower())

    # ----------------------------------------------------------------------------------------------------
    def test_fails_when_unresolved_placeholders_in_prompt(self):
        plan             = _make_plan(python_calls=[_make_call()])
        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[_make_output()],
            final_prompt="The time is {{current_time}}.",
            final_response="It is 9am.",
        )
        self.assertFalse(is_valid)
        self.assertIn("unresolved", message.lower())

    # ----------------------------------------------------------------------------------------------------
    def test_fails_when_final_response_empty(self):
        plan             = _make_plan(python_calls=[_make_call()])
        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[_make_output()],
            final_prompt="The current time is 09:00.",
            final_response="   ",
        )
        self.assertFalse(is_valid)
        self.assertIn("empty", message.lower())

    # ----------------------------------------------------------------------------------------------------
    def test_passes_valid_iteration(self):
        plan             = _make_plan(python_calls=[_make_call()])
        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[_make_output()],
            final_prompt="The current time is 09:00.",
            final_response="It is 9:00 AM.",
        )
        self.assertTrue(is_valid)
        self.assertIn("passed", message.lower())


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
