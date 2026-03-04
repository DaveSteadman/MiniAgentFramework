# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import unittest
from pathlib import Path


# ====================================================================================================
# MARK: RUNNER
# ====================================================================================================
def run_all_tests() -> None:
    tests_dir = Path(__file__).resolve().parent / "code" / "tests"
    loader    = unittest.TestLoader()
    suite     = loader.discover(start_dir=str(tests_dir), pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    sys.exit(0 if result.wasSuccessful() else 1)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    run_all_tests()
