import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = REPO_ROOT / "code"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from skill_executor import execute_tool_call
from skills_catalog_builder import build_tool_definitions
from skills_catalog_builder import load_skills_payload
from skills.FileAccess.file_access_skill import execute_file_instruction


class RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skills_payload = load_skills_payload(CODE_DIR / "skills" / "skills_summary.md")

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

    def test_execute_tool_call_runs_datetime(self) -> None:
        result = execute_tool_call(
            function_name="get_datetime_data",
            arguments={},
            skills_payload=self.skills_payload,
        )
        self.assertEqual(result["function"], "get_datetime_data")
        self.assertIsNotNone(result["result"])
        self.assertNotIn("error", str(result["result"]).lower())

    def test_build_tool_definitions_has_entries(self) -> None:
        tool_defs = build_tool_definitions(self.skills_payload)
        self.assertGreater(len(tool_defs), 0)
        for tool in tool_defs:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("parameters", tool["function"])
            self.assertEqual(tool["function"]["parameters"]["type"], "object")


if __name__ == "__main__":
    unittest.main()