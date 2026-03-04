# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills_catalog_builder import find_skill_files
from skills_catalog_builder import normalize_summary
from skills_catalog_builder import render_summary_document
from skills_catalog_builder import summarize_locally


# ====================================================================================================
# MARK: FIND SKILL FILES
# ====================================================================================================
class TestFindSkillFiles(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_finds_skill_md_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root    = Path(tmpdir)
            skill_a = root / "SkillA" / "skill.md"
            skill_b = root / "SkillB" / "nested" / "skill.md"
            skill_a.parent.mkdir(parents=True)
            skill_b.parent.mkdir(parents=True)
            skill_a.write_text("# SkillA", encoding="utf-8")
            skill_b.write_text("# SkillB", encoding="utf-8")

            result = find_skill_files(skills_root=root)
            self.assertEqual(len(result), 2)

    # ----------------------------------------------------------------------------------------------------
    def test_returns_empty_list_when_no_skill_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_skill_files(skills_root=Path(tmpdir))
            self.assertEqual(result, [])


# ====================================================================================================
# MARK: SUMMARIZE LOCALLY
# ====================================================================================================
class TestSummarizeLocally(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_extracts_title_from_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text("# My Skill\n\n## Purpose\nDoes stuff.", encoding="utf-8")
            result = summarize_locally(skill_md_path=skill_file)
            self.assertEqual(result["skill_name"], "My Skill")

    # ----------------------------------------------------------------------------------------------------
    def test_extracts_purpose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text(
                "# Skill\n\n## Purpose\nProvide the time.\n\n## Input\n- No args.\n",
                encoding="utf-8",
            )
            result = summarize_locally(skill_md_path=skill_file)
            self.assertEqual(result["purpose"], "Provide the time.")

    # ----------------------------------------------------------------------------------------------------
    def test_extracts_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text(
                "# Skill\n- Module: `code/skills/DateTime/datetime_skill.py`\n",
                encoding="utf-8",
            )
            result = summarize_locally(skill_md_path=skill_file)
            self.assertEqual(result["module"], "code/skills/DateTime/datetime_skill.py")

    # ----------------------------------------------------------------------------------------------------
    def test_extracts_functions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text(
                "# Skill\n- Use `get_time()` or `build_prompt(prompt: str)` to call.\n",
                encoding="utf-8",
            )
            result = summarize_locally(skill_md_path=skill_file)
            self.assertIn("get_time()", result["functions"])
            self.assertIn("build_prompt(prompt: str)", result["functions"])

    # ----------------------------------------------------------------------------------------------------
    def test_falls_back_to_parent_name_when_no_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir  = Path(tmpdir) / "MySkill"
            skill_dir.mkdir()
            skill_file = skill_dir / "skill.md"
            skill_file.write_text("No heading here.", encoding="utf-8")
            result = summarize_locally(skill_md_path=skill_file)
            self.assertEqual(result["skill_name"], "MySkill")


# ====================================================================================================
# MARK: NORMALIZE SUMMARY
# ====================================================================================================
class TestNormalizeSummary(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_normalizes_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text("", encoding="utf-8")
            summary = {"skill_name": "Test", "relative_path": "old/path"}
            result  = normalize_summary(summary=summary, skill_md_path=skill_file)
            # relative_path should reflect the actual path, not the old value.
            self.assertNotEqual(result["relative_path"], "old/path")

    # ----------------------------------------------------------------------------------------------------
    def test_converts_string_functions_to_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text("", encoding="utf-8")
            summary = {"skill_name": "Test", "functions": "get_time()", "inputs": [], "outputs": []}
            result  = normalize_summary(summary=summary, skill_md_path=skill_file)
            self.assertEqual(result["functions"], ["get_time()"])

    # ----------------------------------------------------------------------------------------------------
    def test_strips_whitespace_from_list_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "skill.md"
            skill_file.write_text("", encoding="utf-8")
            summary = {"functions": ["  get_time()  ", " build_prompt() "], "inputs": [], "outputs": []}
            result  = normalize_summary(summary=summary, skill_md_path=skill_file)
            self.assertEqual(result["functions"], ["get_time()", "build_prompt()"])


# ====================================================================================================
# MARK: RENDER SUMMARY DOCUMENT
# ====================================================================================================
class TestRenderSummaryDocument(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_rendered_document_contains_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "skills_summary.md"
            summaries   = [{"skill_name": "DateTime Skill", "module": "code/skills/DateTime/datetime_skill.py"}]
            document    = render_summary_document(summaries=summaries, output_path=output_path)
            self.assertIn("DateTime Skill", document)
            self.assertIn("Skills Summary", document)

    # ----------------------------------------------------------------------------------------------------
    def test_rendered_document_is_valid_json_in_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "skills_summary.md"
            summaries   = [{"skill_name": "DateTime Skill"}]
            document    = render_summary_document(summaries=summaries, output_path=output_path)
            # Extract JSON block from rendered document.
            start = document.find("{")
            end   = document.rfind("}") + 1
            payload = json.loads(document[start:end])
            self.assertIn("skills", payload)
            self.assertEqual(payload["skills"][0]["skill_name"], "DateTime Skill")


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
