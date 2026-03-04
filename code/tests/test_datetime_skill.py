# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "DateTime"))

from datetime_skill import build_prompt_with_datetime
from datetime_skill import get_datetime_string


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestGetDatetimeString(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_returns_string(self):
        result = get_datetime_string()
        self.assertIsInstance(result, str)

    # ----------------------------------------------------------------------------------------------------
    def test_starts_with_prefix(self):
        result = get_datetime_string()
        self.assertTrue(result.startswith("Current date/time: "))

    # ----------------------------------------------------------------------------------------------------
    def test_matches_expected_format(self):
        result  = get_datetime_string()
        pattern = r"^Current date/time: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
        self.assertRegex(result, pattern)


# ====================================================================================================
# MARK: BUILD PROMPT WITH DATETIME TESTS
# ====================================================================================================
class TestBuildPromptWithDatetime(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_contains_user_prompt(self):
        result = build_prompt_with_datetime(prompt="tell me the time")
        self.assertIn("tell me the time", result)

    # ----------------------------------------------------------------------------------------------------
    def test_datetime_prefix_appears_first(self):
        result = build_prompt_with_datetime(prompt="my question")
        lines  = result.splitlines()
        self.assertTrue(lines[0].startswith("Current date/time: "))

    # ----------------------------------------------------------------------------------------------------
    def test_prompt_on_second_line(self):
        result = build_prompt_with_datetime(prompt="my question")
        lines  = result.splitlines()
        self.assertEqual(lines[1], "my question")

    # ----------------------------------------------------------------------------------------------------
    def test_empty_prompt_still_returns_datetime(self):
        result = build_prompt_with_datetime(prompt="")
        self.assertIn("Current date/time:", result)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
