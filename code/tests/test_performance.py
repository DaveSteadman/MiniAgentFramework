# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "DateTime"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "SystemInfo"))

from datetime_skill import build_prompt_with_datetime
from datetime_skill import get_datetime_string
from planner_engine import build_fallback_plan
from planner_engine import build_planner_prompt
from planner_engine import extract_first_json_object
from system_info_skill import get_system_info_string


# ====================================================================================================
# MARK: PERFORMANCE THRESHOLDS (seconds)
# ====================================================================================================
MAX_DATETIME_STRING_SECONDS   = 0.1
MAX_SYSTEM_INFO_SECONDS        = 3.0
MAX_JSON_EXTRACTION_SECONDS    = 0.5
MAX_PLANNER_PROMPT_SECONDS     = 0.2
MAX_FALLBACK_PLAN_SECONDS      = 0.1


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestDatetimeSkillPerformance(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_get_datetime_string_is_fast(self):
        start  = time.perf_counter()
        result = get_datetime_string()
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_DATETIME_STRING_SECONDS,
            f"get_datetime_string() took {elapsed:.3f}s, expected < {MAX_DATETIME_STRING_SECONDS}s",
        )

    # ----------------------------------------------------------------------------------------------------
    def test_build_prompt_with_datetime_is_fast(self):
        start   = time.perf_counter()
        result  = build_prompt_with_datetime(prompt="how long does this take?")
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_DATETIME_STRING_SECONDS,
            f"build_prompt_with_datetime() took {elapsed:.3f}s, expected < {MAX_DATETIME_STRING_SECONDS}s",
        )


# ====================================================================================================
# MARK: SYSTEM INFO PERFORMANCE
# ====================================================================================================
class TestSystemInfoSkillPerformance(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_get_system_info_string_within_threshold(self):
        # Subprocess call to ollama --version may be slow when ollama is not installed.
        start   = time.perf_counter()
        result  = get_system_info_string()
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_SYSTEM_INFO_SECONDS,
            f"get_system_info_string() took {elapsed:.3f}s, expected < {MAX_SYSTEM_INFO_SECONDS}s",
        )


# ====================================================================================================
# MARK: PLANNER ENGINE PERFORMANCE
# ====================================================================================================
class TestPlannerEnginePerformance(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_extract_json_from_large_input_is_fast(self):
        # Simulate a realistic LLM response with preamble text before the JSON.
        json_payload = '{"user_prompt": "test", "selected_skills": [], "python_calls": [], "final_prompt_template": ""}'
        large_input  = "Preamble text. " * 500 + json_payload + " Trailing text. " * 500
        start        = time.perf_counter()
        result       = extract_first_json_object(large_input)
        elapsed      = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_JSON_EXTRACTION_SECONDS,
            f"extract_first_json_object() took {elapsed:.3f}s on large input, expected < {MAX_JSON_EXTRACTION_SECONDS}s",
        )

    # ----------------------------------------------------------------------------------------------------
    def test_build_planner_prompt_is_fast(self):
        skills_payload = {
            "skills": [
                {
                    "skill_name": "DateTime Skill",
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "functions": ["get_datetime_string()", "build_prompt_with_datetime(prompt: str)"],
                }
            ]
        }
        start   = time.perf_counter()
        result  = build_planner_prompt(
            user_prompt="what time is it",
            planner_ask="Select skills.",
            skills_payload=skills_payload,
        )
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_PLANNER_PROMPT_SECONDS,
            f"build_planner_prompt() took {elapsed:.3f}s, expected < {MAX_PLANNER_PROMPT_SECONDS}s",
        )

    # ----------------------------------------------------------------------------------------------------
    def test_build_fallback_plan_is_fast(self):
        skills_payload = {
            "skills": [
                {
                    "skill_name": "DateTime Skill",
                    "relative_path": "code/skills/DateTime/skill.md",
                    "module": "code/skills/DateTime/datetime_skill.py",
                    "functions": ["build_prompt_with_datetime(prompt: str)"],
                }
            ]
        }
        start   = time.perf_counter()
        result  = build_fallback_plan(user_prompt="what time is it", skills_payload=skills_payload)
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        self.assertLess(
            elapsed,
            MAX_FALLBACK_PLAN_SECONDS,
            f"build_fallback_plan() took {elapsed:.3f}s, expected < {MAX_FALLBACK_PLAN_SECONDS}s",
        )


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
