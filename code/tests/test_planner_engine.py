# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner_engine import build_fallback_plan
from planner_engine import build_planner_prompt
from planner_engine import ExecutionPlan
from planner_engine import extract_first_json_object
from planner_engine import parse_execution_plan


# ====================================================================================================
# MARK: EXTRACT JSON
# ====================================================================================================
class TestExtractFirstJsonObject(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_extracts_bare_object(self):
        text   = '{"key": "value"}'
        result = extract_first_json_object(text)
        self.assertEqual(json.loads(result), {"key": "value"})

    # ----------------------------------------------------------------------------------------------------
    def test_extracts_with_preamble(self):
        text   = "Some preamble text\n\n{\"a\": 1}"
        result = extract_first_json_object(text)
        self.assertEqual(json.loads(result), {"a": 1})

    # ----------------------------------------------------------------------------------------------------
    def test_extracts_nested_object(self):
        text   = 'outer {"inner": {"nested": true}} trailing'
        result = extract_first_json_object(text)
        self.assertEqual(json.loads(result), {"inner": {"nested": True}})

    # ----------------------------------------------------------------------------------------------------
    def test_handles_escaped_braces_in_string(self):
        text   = '{"key": "value with {braces}"}'
        result = extract_first_json_object(text)
        self.assertEqual(json.loads(result), {"key": "value with {braces}"})

    # ----------------------------------------------------------------------------------------------------
    def test_raises_when_no_json(self):
        with self.assertRaises(RuntimeError):
            extract_first_json_object("no json here")

    # ----------------------------------------------------------------------------------------------------
    def test_raises_when_incomplete_json(self):
        with self.assertRaises(RuntimeError):
            extract_first_json_object('{"unclosed": "object"')


# ====================================================================================================
# MARK: PARSE EXECUTION PLAN
# ====================================================================================================
class TestParseExecutionPlan(unittest.TestCase):
    def _valid_plan_dict(self) -> dict:
        return {
            "user_prompt": "output the time",
            "selected_skills": [
                {
                    "skill_name": "DateTime Skill",
                    "relative_path": "code/skills/DateTime/skill.md",
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "reason": "Needed to provide current time.",
                }
            ],
            "python_calls": [
                {
                    "order": 1,
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "function": "get_datetime_string",
                    "arguments": {},
                }
            ],
            "final_prompt_template": "Use datetime output as context.",
        }

    # ----------------------------------------------------------------------------------------------------
    def test_parses_valid_plan(self):
        plan = parse_execution_plan(self._valid_plan_dict())
        self.assertIsInstance(plan, ExecutionPlan)
        self.assertEqual(plan.user_prompt, "output the time")
        self.assertEqual(len(plan.selected_skills), 1)
        self.assertEqual(len(plan.python_calls), 1)
        self.assertEqual(plan.python_calls[0].function, "get_datetime_string")

    # ----------------------------------------------------------------------------------------------------
    def test_raises_on_missing_key(self):
        plan_dict = self._valid_plan_dict()
        del plan_dict["python_calls"]
        with self.assertRaises(RuntimeError):
            parse_execution_plan(plan_dict)

    # ----------------------------------------------------------------------------------------------------
    def test_raises_when_selected_skills_not_list(self):
        plan_dict = self._valid_plan_dict()
        plan_dict["selected_skills"] = "not a list"
        with self.assertRaises(RuntimeError):
            parse_execution_plan(plan_dict)

    # ----------------------------------------------------------------------------------------------------
    def test_raises_when_arguments_not_dict(self):
        plan_dict = self._valid_plan_dict()
        plan_dict["python_calls"][0]["arguments"] = "not a dict"
        with self.assertRaises(RuntimeError):
            parse_execution_plan(plan_dict)

    # ----------------------------------------------------------------------------------------------------
    def test_python_calls_sorted_by_order(self):
        plan_dict = self._valid_plan_dict()
        plan_dict["python_calls"] = [
            {"order": 3, "module": "m", "function": "f3", "arguments": {}},
            {"order": 1, "module": "m", "function": "f1", "arguments": {}},
            {"order": 2, "module": "m", "function": "f2", "arguments": {}},
        ]
        plan = parse_execution_plan(plan_dict)
        orders = [call.order for call in plan.python_calls]
        self.assertEqual(orders, [1, 2, 3])

    # ----------------------------------------------------------------------------------------------------
    def test_to_dict_round_trip(self):
        original = self._valid_plan_dict()
        plan     = parse_execution_plan(original)
        restored = plan.to_dict()
        self.assertEqual(restored["user_prompt"], original["user_prompt"])
        self.assertEqual(len(restored["python_calls"]), 1)


# ====================================================================================================
# MARK: BUILD PLANNER PROMPT
# ====================================================================================================
class TestBuildPlannerPrompt(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_prompt_contains_user_prompt(self):
        prompt = build_planner_prompt(
            user_prompt="tell me the time",
            planner_ask="Select skills for this prompt.",
            skills_payload={"skills": []},
        )
        self.assertIn("tell me the time", prompt)

    # ----------------------------------------------------------------------------------------------------
    def test_prompt_contains_planner_ask(self):
        prompt = build_planner_prompt(
            user_prompt="hello",
            planner_ask="Custom planner instruction.",
            skills_payload={"skills": []},
        )
        self.assertIn("Custom planner instruction.", prompt)

    # ----------------------------------------------------------------------------------------------------
    def test_prompt_contains_json_schema_hint(self):
        prompt = build_planner_prompt(
            user_prompt="hello",
            planner_ask="select skills",
            skills_payload={"skills": []},
        )
        self.assertIn("python_calls", prompt)
        self.assertIn("selected_skills", prompt)


# ====================================================================================================
# MARK: BUILD FALLBACK PLAN
# ====================================================================================================
class TestBuildFallbackPlan(unittest.TestCase):
    def _skills_payload_with_datetime(self) -> dict:
        return {
            "skills": [
                {
                    "skill_name": "DateTime Skill",
                    "relative_path": "code/skills/DateTime/skill.md",
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "functions": ["get_datetime_string()", "build_prompt_with_datetime(prompt: str)"],
                }
            ]
        }

    # ----------------------------------------------------------------------------------------------------
    def test_fallback_selects_datetime_skill(self):
        plan = build_fallback_plan(
            user_prompt="what time is it",
            skills_payload=self._skills_payload_with_datetime(),
        )
        self.assertEqual(len(plan.python_calls), 1)
        self.assertEqual(plan.python_calls[0].function, "build_prompt_with_datetime")

    # ----------------------------------------------------------------------------------------------------
    def test_fallback_empty_plan_when_no_datetime_skill(self):
        plan = build_fallback_plan(
            user_prompt="hello",
            skills_payload={"skills": []},
        )
        self.assertEqual(plan.python_calls, [])
        self.assertEqual(plan.selected_skills, [])


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
