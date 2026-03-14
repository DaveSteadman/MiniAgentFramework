import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = REPO_ROOT / "code"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from orchestration_validation import validate_orchestration_iteration
from planner_engine import ExecutionPlan
from planner_engine import PythonCall
from planner_engine import SelectedSkill
from planner_engine import build_fallback_plan
from planner_engine import load_skills_payload
from skills.FileAccess.file_access_skill import execute_file_instruction


class RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skills_payload = load_skills_payload(CODE_DIR / "skills" / "skills_summary.md")

    def test_combined_system_file_fallback_plan_chains_write(self) -> None:
        prompt = "write the system information to a data/systemstats.csv spreadsheet"

        plan = build_fallback_plan(user_prompt=prompt, skills_payload=self.skills_payload)

        self.assertEqual([call.function for call in plan.python_calls], ["get_system_info_dict", "write_text_file"])
        self.assertEqual(plan.python_calls[1].arguments["file_path"], "data/systemstats.csv")
        self.assertEqual(plan.python_calls[1].arguments["text"], "{{output_of_previous_call}}")

    def test_execute_file_instruction_writes_system_info_csv(self) -> None:
        prompt = "write the system information to a data/test_systemstats_regression.csv spreadsheet"
        output_path = REPO_ROOT / "data" / "test_systemstats_regression.csv"

        if output_path.exists():
            output_path.unlink()

        try:
            result = execute_file_instruction(prompt)
            self.assertEqual(result, "Wrote data/test_systemstats_regression.csv")
            self.assertTrue(output_path.exists())

            content = output_path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("key,value\n"))
            self.assertIn("os,", content)
            self.assertIn("python,", content)
        finally:
            if output_path.exists():
                output_path.unlink()

    def test_validation_rejects_failed_python_call_outputs(self) -> None:
        plan = ExecutionPlan(
            user_prompt="write the system information to a data/systemstats.csv spreadsheet",
            selected_skills=[
                SelectedSkill(
                    skill_name="FileAccess Skill",
                    relative_path="code/skills/FileAccess/skill.md",
                    module="code/skills/FileAccess/file_access_skill.py",
                    reason="Test fixture",
                )
            ],
            python_calls=[
                PythonCall(
                    order=1,
                    module="code/skills/FileAccess/file_access_skill.py",
                    function="execute_file_instruction",
                    arguments={"user_prompt": "write the system information to a data/systemstats.csv spreadsheet"},
                )
            ],
            final_prompt_template="Report the result of the file operation to the user.",
        )

        is_valid, message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=[
                {
                    "order": 1,
                    "module": "code/skills/FileAccess/file_access_skill.py",
                    "function": "execute_file_instruction",
                    "arguments": {"user_prompt": plan.user_prompt},
                    "result": "No file path found in instruction. Include 'file <path>'.",
                }
            ],
            final_prompt="Prompt text",
            final_response="The system information has been written to data/systemstats.csv.",
        )

        self.assertFalse(is_valid)
        self.assertIn("Python call 1", message)
        self.assertIn("No file path found", message)


if __name__ == "__main__":
    unittest.main()