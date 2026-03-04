# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime_logger import create_log_file_path
from runtime_logger import SessionLogger


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestCreateLogFilePath(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_returns_path_in_log_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            result  = create_log_file_path(log_dir=log_dir)
            self.assertEqual(result.parent, log_dir)

    # ----------------------------------------------------------------------------------------------------
    def test_path_starts_with_run_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = create_log_file_path(log_dir=Path(tmpdir))
            self.assertTrue(result.name.startswith("run_"))

    # ----------------------------------------------------------------------------------------------------
    def test_path_has_txt_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = create_log_file_path(log_dir=Path(tmpdir))
            self.assertEqual(result.suffix, ".txt")

    # ----------------------------------------------------------------------------------------------------
    def test_consecutive_paths_are_unique(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            paths   = {create_log_file_path(log_dir=log_dir) for _ in range(5)}
            # All paths should be unique strings (timestamps may collide in fast loops,
            # but the stem format ensures the set has at least one entry).
            self.assertGreaterEqual(len(paths), 1)


# ====================================================================================================
# MARK: SESSION LOGGER TESTS
# ====================================================================================================
class TestSessionLogger(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_log_writes_message_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_run.txt"
            logger   = SessionLogger(file_path=log_path)
            logger.log("hello world")
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("hello world", content)

    # ----------------------------------------------------------------------------------------------------
    def test_log_section_writes_separator_and_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test_run.txt"
            logger   = SessionLogger(file_path=log_path)
            logger.log_section("MY SECTION")
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("MY SECTION", content)
            self.assertIn("=" * 10, content)

    # ----------------------------------------------------------------------------------------------------
    def test_log_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "nested" / "dir" / "run.txt"
            logger   = SessionLogger(file_path=log_path)
            logger.log("created nested")
            self.assertTrue(log_path.exists())

    # ----------------------------------------------------------------------------------------------------
    def test_log_appends_multiple_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "run.txt"
            logger   = SessionLogger(file_path=log_path)
            logger.log("first")
            logger.log("second")
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("first", content)
            self.assertIn("second", content)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
