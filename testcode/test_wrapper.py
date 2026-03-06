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
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
REPO_ROOT          = Path(__file__).resolve().parent.parent
MAIN_SCRIPT        = REPO_ROOT / "code" / "main.py"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_PROMPTS_FILE = Path(__file__).resolve().parent / "prompts" / "default_prompts.json"

DEFAULT_PROMPTS = None  # Loaded from DEFAULT_PROMPTS_FILE at runtime.

# Maximum time in seconds to wait for a single framework invocation before aborting.
SUBPROCESS_TIMEOUT_SECONDS = 300

CSV_FIELDS = ["timestamp", "prompt", "final_output", "duration_seconds", "exit_code", "log_file", "stderr"]


# ====================================================================================================
# MARK: PROMPTS LOADING
# ====================================================================================================
def load_prompts_file(path: Path) -> list[str]:
    """Load a JSON array of prompt strings from a file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Prompts file must contain a JSON array: {path}")
    return [str(item) for item in data]


# ====================================================================================================
# MARK: INVOCATION
# ====================================================================================================
def invoke_framework(prompt: str, model: str | None = None) -> tuple[float, int, str, str]:
    """Invoke code/main.py with the given prompt and return (duration, exit_code, stdout, stderr)."""
    start_time = time.monotonic()

    cmd = [sys.executable, str(MAIN_SCRIPT), "--user-prompt", prompt]
    if model:
        cmd += ["--model", model]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    duration = time.monotonic() - start_time
    return duration, result.returncode, result.stdout, result.stderr


# ----------------------------------------------------------------------------------------------------
def extract_log_file(stdout_text: str) -> str:
    for line in stdout_text.splitlines():
        if line.strip().startswith("Log file:"):
            return line.split("Log file:", maxsplit=1)[1].strip()
    return ""


# ----------------------------------------------------------------------------------------------------
def _extract_final_output_from_lines(lines: list[str]) -> str:
    final_section_index = -1
    for index, line in enumerate(lines):
        if "FINAL LLM EXECUTION" in line:
            final_section_index = index
            break

    if final_section_index < 0:
        return ""

    collected_lines = []
    for line in lines[final_section_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("ITERATION"):
            break
        if stripped.startswith("="):
            if collected_lines:
                break
            continue
        if not stripped and not collected_lines:
            continue
        collected_lines.append(line)

    return "\n".join(item.rstrip() for item in collected_lines).strip()


# ----------------------------------------------------------------------------------------------------
def extract_final_output(stdout_text: str, stderr_text: str, log_file: str) -> str:
    if log_file:
        try:
            log_lines = Path(log_file).read_text(encoding="utf-8").splitlines()
            output_from_log = _extract_final_output_from_lines(log_lines)
            if output_from_log:
                return output_from_log.replace("\u202f", " ")
        except Exception:
            pass

    lines = stdout_text.splitlines()
    parsed_output = _extract_final_output_from_lines(lines)
    if parsed_output:
        return parsed_output.replace("\u202f", " ")

    last_non_empty_stdout = ""
    for line in reversed(lines):
        if line.strip():
            last_non_empty_stdout = line.strip()
            break

    if last_non_empty_stdout:
        return last_non_empty_stdout.replace("\u202f", " ")

    return stderr_text.strip().replace("\u202f", " ")


# ====================================================================================================
# MARK: CSV OUTPUT
# ====================================================================================================
def build_output_path(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"test_results_{timestamp}.csv"


# ----------------------------------------------------------------------------------------------------
def initialize_csv(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()


# ----------------------------------------------------------------------------------------------------
def append_csv_row(output_path: Path, row: dict) -> None:
    sanitized_row = {}
    for key, value in row.items():
        if isinstance(value, str):
            sanitized_row[key] = value.replace("\r", " ")
        else:
            sanitized_row[key] = value

    with output_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
        )
        writer.writerow(sanitized_row)
        csv_file.flush()
        os.fsync(csv_file.fileno())


# ====================================================================================================
# MARK: TEST RUNNER
# ====================================================================================================
def run_tests(prompts: list[str], output_dir: Path, model: str | None = None) -> Path:
    output_path = build_output_path(output_dir)
    initialize_csv(output_path)
    model_label = f" (model: {model})" if model else ""
    print(f"Results file initialized: {output_path}{model_label}")

    total_prompts = len(prompts)

    for index, prompt in enumerate(prompts, start=1):
        run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{run_timestamp}] Running prompt {index}/{total_prompts}: {prompt!r}")

        stdout = ""
        stderr = ""
        exit_code = -1
        duration = 0.0
        log_file = ""
        final_output = ""

        try:
            duration, exit_code, stdout, stderr = invoke_framework(prompt, model=model)
            log_file     = extract_log_file(stdout_text=stdout)
            final_output = extract_final_output(stdout_text=stdout, stderr_text=stderr, log_file=log_file)
        except subprocess.TimeoutExpired as timeout_error:
            # Record timeout as a failed row and continue running the rest of prompts.
            duration = float(SUBPROCESS_TIMEOUT_SECONDS)
            exit_code = 124
            stderr = f"Timeout after {SUBPROCESS_TIMEOUT_SECONDS}s: {timeout_error}"
            final_output = ""
        except KeyboardInterrupt:
            # Persist an interrupted row and stop the run gracefully.
            exit_code = 130
            stderr = "Interrupted by user (KeyboardInterrupt)."
            final_output = ""
        except Exception as unexpected_error:
            # Record unexpected wrapper failures in CSV so no prompt is silently dropped.
            exit_code = 125
            stderr = f"Wrapper error: {unexpected_error}"
            final_output = ""

        row = {
            "timestamp":        run_timestamp,
            "prompt":           prompt,
            "final_output":     final_output,
            "duration_seconds": f"{duration:.3f}",
            "exit_code":        exit_code,
            "log_file":         log_file,
            "stderr":           stderr.strip(),
        }
        append_csv_row(output_path=output_path, row=row)

        status_label = "OK" if exit_code == 0 else "FAIL"
        print(f"  [{status_label}] duration={duration:.3f}s  exit_code={exit_code}")

        if exit_code == 130:
            print("Interrupted by user, ending test run after recording this prompt.")
            break

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
        default=None,
        help="One or more user prompts to test (overrides --prompts-file).",
    )
    parser.add_argument(
        "--prompts-file",
        type=Path,
        default=None,
        help="Path to a JSON file containing an array of prompt strings.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the CSV results file will be written.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Ollama model alias to pass to main.py (overrides its default).",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: ENTRYPOINT
# ====================================================================================================
if __name__ == "__main__":
    args = parse_args()

    if args.prompts:
        prompts = args.prompts
    elif args.prompts_file:
        prompts = load_prompts_file(args.prompts_file)
    else:
        prompts = load_prompts_file(DEFAULT_PROMPTS_FILE)

    run_tests(prompts=prompts, output_dir=args.output_dir, model=args.model)
