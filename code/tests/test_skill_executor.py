# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner_engine import PythonCall
from skill_executor import _build_allowlist
from skill_executor import _normalize_module_path
from skill_executor import _resolve_argument_placeholders
from skill_executor import _validate_call_allowed


# ====================================================================================================
# MARK: NORMALIZE MODULE PATH
# ====================================================================================================
class TestNormalizeModulePath(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_strips_py_extension(self):
        result = _normalize_module_path("code/skills/DateTime/datetime_skill.py")
        self.assertEqual(result, "code/skills/DateTime/datetime_skill")

    # ----------------------------------------------------------------------------------------------------
    def test_strips_leading_dotslash(self):
        result = _normalize_module_path("./code/skills/DateTime/datetime_skill.py")
        self.assertEqual(result, "code/skills/DateTime/datetime_skill")

    # ----------------------------------------------------------------------------------------------------
    def test_normalizes_backslashes(self):
        result = _normalize_module_path("code\\skills\\DateTime\\datetime_skill.py")
        self.assertEqual(result, "code/skills/DateTime/datetime_skill")

    # ----------------------------------------------------------------------------------------------------
    def test_no_extension_unchanged(self):
        result = _normalize_module_path("code/skills/DateTime/datetime_skill")
        self.assertEqual(result, "code/skills/DateTime/datetime_skill")


# ====================================================================================================
# MARK: BUILD ALLOWLIST
# ====================================================================================================
class TestBuildAllowlist(unittest.TestCase):
    def _make_skills_payload(self) -> dict:
        return {
            "skills": [
                {
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "functions": ["get_datetime_string()", "build_prompt_with_datetime(prompt: str)"],
                },
                {
                    "module": "code/skills/SystemInfo/system_info_skill.py",
                    "functions": ["get_system_info_string", "build_prompt_with_system_info"],
                },
            ]
        }

    # ----------------------------------------------------------------------------------------------------
    def test_allowlist_contains_expected_entries(self):
        allowlist = _build_allowlist(self._make_skills_payload())
        self.assertIn(("code/skills/DateTime/datetime_skill", "get_datetime_string"), allowlist)
        self.assertIn(("code/skills/DateTime/datetime_skill", "build_prompt_with_datetime"), allowlist)
        self.assertIn(("code/skills/SystemInfo/system_info_skill", "get_system_info_string"), allowlist)

    # ----------------------------------------------------------------------------------------------------
    def test_allowlist_strips_function_signatures(self):
        # Functions listed with "(prompt: str)" should be normalized to just the name.
        allowlist = _build_allowlist(self._make_skills_payload())
        self.assertIn(("code/skills/DateTime/datetime_skill", "build_prompt_with_datetime"), allowlist)

    # ----------------------------------------------------------------------------------------------------
    def test_allowlist_empty_for_empty_payload(self):
        allowlist = _build_allowlist({"skills": []})
        self.assertEqual(len(allowlist), 0)


# ====================================================================================================
# MARK: VALIDATE CALL ALLOWED
# ====================================================================================================
class TestValidateCallAllowed(unittest.TestCase):
    def _allowlist(self) -> set:
        return {("code/skills/DateTime/datetime_skill", "get_datetime_string")}

    def _make_call(self, module: str, function: str) -> PythonCall:
        return PythonCall(order=1, module=module, function=function, arguments={})

    # ----------------------------------------------------------------------------------------------------
    def test_does_not_raise_for_allowed_call(self):
        call = self._make_call(
            module="code/skills/DateTime/datetime_skill.py",
            function="get_datetime_string",
        )
        _validate_call_allowed(call=call, allowlist=self._allowlist())

    # ----------------------------------------------------------------------------------------------------
    def test_raises_for_disallowed_call(self):
        call = self._make_call(
            module="code/skills/DateTime/datetime_skill.py",
            function="evil_function",
        )
        with self.assertRaises(RuntimeError):
            _validate_call_allowed(call=call, allowlist=self._allowlist())


# ====================================================================================================
# MARK: RESOLVE ARGUMENT PLACEHOLDERS
# ====================================================================================================
class TestResolveArgumentPlaceholders(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_resolves_user_prompt(self):
        result = _resolve_argument_placeholders(
            call_arguments={"prompt": "{{user_prompt}}"},
            previous_outputs=[],
            user_prompt="what time is it",
        )
        self.assertEqual(result["prompt"], "what time is it")

    # ----------------------------------------------------------------------------------------------------
    def test_resolves_output_of_first_call(self):
        result = _resolve_argument_placeholders(
            call_arguments={"context": "{{output_of_first_call}}"},
            previous_outputs=["first result", "second result"],
            user_prompt="hello",
        )
        self.assertEqual(result["context"], "first result")

    # ----------------------------------------------------------------------------------------------------
    def test_resolves_output_of_previous_call(self):
        result = _resolve_argument_placeholders(
            call_arguments={"context": "{{output_of_previous_call}}"},
            previous_outputs=["first result", "second result"],
            user_prompt="hello",
        )
        self.assertEqual(result["context"], "second result")

    # ----------------------------------------------------------------------------------------------------
    def test_leaves_unknown_placeholders_unchanged(self):
        result = _resolve_argument_placeholders(
            call_arguments={"value": "{{unknown_placeholder}}"},
            previous_outputs=[],
            user_prompt="hello",
        )
        self.assertEqual(result["value"], "{{unknown_placeholder}}")

    # ----------------------------------------------------------------------------------------------------
    def test_leaves_non_string_values_unchanged(self):
        result = _resolve_argument_placeholders(
            call_arguments={"count": 42, "flag": True},
            previous_outputs=[],
            user_prompt="hello",
        )
        self.assertEqual(result["count"], 42)
        self.assertTrue(result["flag"])

    # ----------------------------------------------------------------------------------------------------
    def test_first_call_placeholder_not_resolved_without_outputs(self):
        result = _resolve_argument_placeholders(
            call_arguments={"context": "{{output_of_first_call}}"},
            previous_outputs=[],
            user_prompt="hello",
        )
        self.assertEqual(result["context"], "{{output_of_first_call}}")


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
