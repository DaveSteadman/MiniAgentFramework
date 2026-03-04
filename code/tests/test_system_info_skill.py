# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "SystemInfo"))

from system_info_skill import build_prompt_with_system_info
from system_info_skill import get_system_info_string


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestGetSystemInfoString(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_returns_string(self):
        result = get_system_info_string()
        self.assertIsInstance(result, str)

    # ----------------------------------------------------------------------------------------------------
    def test_starts_with_prefix(self):
        result = get_system_info_string()
        self.assertTrue(result.startswith("System info: "))

    # ----------------------------------------------------------------------------------------------------
    def test_contains_python_version(self):
        result = get_system_info_string()
        self.assertIn("python=", result)

    # ----------------------------------------------------------------------------------------------------
    def test_contains_ollama_version_field(self):
        result = get_system_info_string()
        self.assertIn("ollama=", result)


# ====================================================================================================
# MARK: BUILD PROMPT WITH SYSTEM INFO TESTS
# ====================================================================================================
class TestBuildPromptWithSystemInfo(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_returns_string(self):
        result = build_prompt_with_system_info(prompt="what version?")
        self.assertIsInstance(result, str)

    # ----------------------------------------------------------------------------------------------------
    def test_returns_system_info_content(self):
        result = build_prompt_with_system_info(prompt="what version?")
        self.assertIn("System info:", result)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
