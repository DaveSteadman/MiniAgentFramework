# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# External test wrapper for MiniAgentFramework.
#
# Invokes the framework as a full system via subprocess (as a user would) and captures each
# prompt-response cycle with accurate timing. Results are written to a structured CSV file that
# uses proper quoting so that fields containing commas or newlines do not cause parsing errors.
#
# Usage:
#   python testcode/test_wrapper.py
#   python testcode/test_wrapper.py --output-dir testcode/results
#   python testcode/test_wrapper.py --prompts "output the time" "what is today's date"
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
REPO_ROOT          = Path(__file__).resolve().parent.parent
MAIN_SCRIPT        = REPO_ROOT / "code" / "main.py"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "results"

DEFAULT_PROMPTS = [
    "output the time",
    "what is today's date",
    "what version of python is running",
]

# Maximum time in seconds to wait for a single framework invocation before aborting.
SUBPROCESS_TIMEOUT_SECONDS = 300

CSV_FIELDS = ["timestamp", "prompt", "duration_seconds", "exit_code", "response", "stderr"]


# ====================================================================================================
# MARK: INVOCATION
# ====================================================================================================
def invoke_framework(prompt: str) -> tuple[float, int, str, str]:
    """Invoke code/main.py with the given prompt and return (duration, exit_code, stdout, stderr)."""
    start_time = time.monotonic()

    result = subprocess.run(
        [sys.executable, str(MAIN_SCRIPT), "--user-prompt", prompt],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    duration = time.monotonic() - start_time
    return duration, result.returncode, result.stdout, result.stderr


# ====================================================================================================
# MARK: CSV OUTPUT
# ====================================================================================================
def build_output_path(output_dir: Path) -> Path:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return output_dir / f"test_results_{timestamp}.csv"


# ----------------------------------------------------------------------------------------------------
def write_csv_results(output_path: Path, rows: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)


# ====================================================================================================
# MARK: TEST RUNNER
# ====================================================================================================
def run_tests(prompts: list[str], output_dir: Path) -> Path:
    rows = []

    for prompt in prompts:
        run_timestamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        print(f"[{run_timestamp}] Running prompt: {prompt!r}")

        duration, exit_code, stdout, stderr = invoke_framework(prompt)

        row = {
            "timestamp":        run_timestamp,
            "prompt":           prompt,
            "duration_seconds": f"{duration:.3f}",
            "exit_code":        exit_code,
            "response":         stdout.strip(),
            "stderr":           stderr.strip(),
        }
        rows.append(row)

        status_label = "OK" if exit_code == 0 else "FAIL"
        print(f"  [{status_label}] duration={duration:.3f}s  exit_code={exit_code}")

    output_path = build_output_path(output_dir)
    write_csv_results(output_path, rows)
    print(f"\nResults written to: {output_path}")
    return output_path


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="External test wrapper for MiniAgentFramework. "
                    "Invokes the framework as a subprocess and records results to CSV."
    )
    parser.add_argument(
        "--prompts",
        nargs="+",
        default=DEFAULT_PROMPTS,
        help="One or more user prompts to test.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the CSV results file will be written.",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: ENTRYPOINT
# ====================================================================================================
if __name__ == "__main__":
    args = parse_args()
    run_tests(prompts=args.prompts, output_dir=args.output_dir)
