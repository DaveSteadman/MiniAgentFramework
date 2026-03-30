# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# External test wrapper for MiniAgentFramework.
#
# Invokes the framework as a full system via subprocess and captures each prompt-response cycle
# with accurate timing. Results are written to a structured CSV file that uses proper quoting
# so that fields containing commas or newlines do not cause parsing errors.
#
# This module is invoked as a subprocess by the /test slash command in slash_commands.py.
# It is not intended to be run interactively from the command line.
#
# Prompts files are JSON arrays whose elements are either:
#   - A plain string        -- single standalone prompt (original format, unchanged)
#   - An exchange object    -- multi-turn sequence sharing ConversationHistory + SessionContext:
#       {
#           "exchange": "label",
#           "turns": [
#               { "user": "first turn prompt" },
#               { "user": "follow-up?", "assert": "contains|expected text" }
#           ]
#       }
#     Supported assert expressions (optional, one per turn):
#       contains|<text>   -- final_output must contain <text> (case-insensitive)
#       not_contains|<text> -- final_output must NOT contain <text> (case-insensitive)
#       not_empty         -- final_output must be non-empty
#       exit_code|<n>     -- overall exchange exit code must equal <n>
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
REPO_ROOT            = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))
from workspace_utils import get_test_results_dir  # noqa: E402

MAIN_SCRIPT        = REPO_ROOT / "code" / "main.py"
DEFAULT_OUTPUT_DIR = get_test_results_dir()

# Maximum time in seconds to wait for a single framework invocation before aborting.
SUBPROCESS_TIMEOUT_SECONDS = 300

CSV_FIELDS = ["timestamp", "source_file", "prompt", "exchange_name", "turn_index",
              "final_output", "assert_result", "duration_seconds", "exit_code", "log_file", "stderr"]


# ====================================================================================================
# MARK: PROMPTS LOADING
# ====================================================================================================
def load_prompts_file(path: Path) -> list:
    """Load a JSON array of prompt strings or exchange objects from a file.

    Returns a mixed list: each element is either a plain str (existing format)
    or an exchange dict with keys 'exchange' and 'turns'.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Prompts file must contain a JSON array: {path}")
    result = []
    for item in data:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and "exchange" in item and "turns" in item:
            result.append(item)
        else:
            result.append(str(item))   # best-effort coerce unknown entries
    return result


# ====================================================================================================
# MARK: INVOCATION
# ====================================================================================================
def invoke_framework(
    prompt: str,
    model: str | None = None,
    ollama_host: str | None = None,
) -> tuple[float, int, str, str]:
    """Invoke code/main.py with the given prompt and return (duration, exit_code, stdout, stderr).

    Routes through --chat-sequence-file (single-element array) so the output is emitted
    in the structured [TURN 1] Agent: format, consistent with exchange mode and parseable
    by _parse_turn_outputs.
    """
    return invoke_exchange(
        [prompt],
        model=model,
        ollama_host=ollama_host,
    )


# ----------------------------------------------------------------------------------------------------
def invoke_exchange(
    turn_prompts: list[str],
    model: str | None = None,
    ollama_host: str | None = None,
) -> tuple[float, int, str, str]:
    """Run a list of prompts as a shared-history exchange via --chat-sequence-file.

    Returns (duration, exit_code, stdout, stderr) for the whole exchange.
    """
    start_time = time.monotonic()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(turn_prompts, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        cmd = [sys.executable, str(MAIN_SCRIPT), "--chat-sequence-file", tmp_path]
        if model:
            cmd += ["--model", model]
        if ollama_host:
            cmd += ["--ollama-host", ollama_host]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=SUBPROCESS_TIMEOUT_SECONDS * len(turn_prompts),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    duration = time.monotonic() - start_time
    return duration, result.returncode, result.stdout, result.stderr


# ----------------------------------------------------------------------------------------------------
def extract_log_file(stdout_text: str) -> str:
    for line in stdout_text.splitlines():
        if line.strip().startswith("Log file:"):
            return line.split("Log file:", maxsplit=1)[1].strip()
    return ""


# ----------------------------------------------------------------------------------------------------
def _parse_turn_outputs(stdout_text: str) -> dict[int, str]:
    """Parse [TURN N] Agent: lines from a chat-sequence stdout into {turn_idx: response}."""
    outputs: dict[int, str] = {}
    current_turn: int | None = None
    current_lines: list[str] = []

    for line in stdout_text.splitlines():
        agent_match = line.startswith("[TURN ") and "] Agent: " in line
        if agent_match:
            # Flush any previous turn accumulation.
            if current_turn is not None:
                outputs[current_turn] = "\n".join(current_lines).strip()
            bracket_end = line.index("]")
            current_turn = int(line[6:bracket_end])
            current_lines = [line.split("] Agent: ", 1)[1]]
        elif current_turn is not None:
            # Check if a new TURN marker starts (tokens line or next turn).
            if line.startswith(f"[TURN {current_turn}] tokens="):
                outputs[current_turn] = "\n".join(current_lines).strip()
                current_turn = None
                current_lines = []
            elif line.startswith("[TURN "):
                outputs[current_turn] = "\n".join(current_lines).strip()
                current_turn = None
                current_lines = []
            else:
                current_lines.append(line)

    if current_turn is not None:
        outputs[current_turn] = "\n".join(current_lines).strip()

    return outputs


# ----------------------------------------------------------------------------------------------------
def _parse_turn_metrics(stdout_text: str) -> dict[int, tuple[int, str]]:
    """Parse [TURN N] tokens=<n> tps=<f> lines into {turn_idx: (tokens, tps_str)}."""
    metrics: dict[int, tuple[int, str]] = {}
    pattern = re.compile(r"^\[TURN\s+(\d+)\]\s+tokens=(\d+)\s+tps=([0-9.]+)$")
    for line in stdout_text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        metrics[int(match.group(1))] = (int(match.group(2)), match.group(3))
    return metrics


# ----------------------------------------------------------------------------------------------------
def _evaluate_assert(expression: str, final_output: str, exit_code: int) -> str:
    """Evaluate an assert expression against outputs.  Returns 'PASS', 'FAIL', or 'SKIP'."""
    if not expression:
        return "SKIP"
    op, _, value = expression.partition("|")
    op = op.strip().lower()
    if op == "contains":
        return "PASS" if value.lower() in final_output.lower() else "FAIL"
    if op == "not_contains":
        return "PASS" if value.lower() not in final_output.lower() else "FAIL"
    if op == "not_empty":
        return "PASS" if final_output.strip() else "FAIL"
    if op == "exit_code":
        try:
            return "PASS" if exit_code == int(value) else "FAIL"
        except ValueError:
            return "SKIP"
    return "SKIP"


# ----------------------------------------------------------------------------------------------------
def extract_final_output(stdout_text: str) -> str:
    """Extract the agent response from structured [TURN 1] Agent: output."""
    return _parse_turn_outputs(stdout_text).get(1, "").replace("\u202f", " ")


# ====================================================================================================
# MARK: CSV OUTPUT
# ====================================================================================================
def build_output_path(output_dir: Path) -> Path:
    now      = datetime.now()
    date_dir = output_dir / now.strftime("%Y-%m-%d")
    return date_dir / f"test_results_{now.strftime('%Y%m%d_%H%M%S')}.csv"


# ----------------------------------------------------------------------------------------------------
def initialize_csv(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Only write the header row when the file is new or empty so that
    # multiple test files can be appended to one shared results file.
    is_new = not output_path.exists() or output_path.stat().st_size == 0
    with output_path.open("a", newline="", encoding="utf-8") as csv_file:
        if is_new:
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


# ----------------------------------------------------------------------------------------------------
def _base_row(run_timestamp: str, source_file: str, prompt: str, exchange_name: str = "", turn_index: int = 0) -> dict:
    """Return a pre-populated CSV row dict with all fields at safe defaults."""
    return {
        "timestamp":        run_timestamp,
        "source_file":      source_file,
        "prompt":           prompt,
        "exchange_name":    exchange_name,
        "turn_index":       turn_index,
        "final_output":     "",
        "assert_result":    "",
        "duration_seconds": "0.000",
        "exit_code":        -1,
        "log_file":         "",
        "stderr":           "",
    }


# ====================================================================================================
# MARK: TEST RUNNER
# ====================================================================================================
def run_tests(
    prompts: list,
    output_dir: Path,
    model: str | None = None,
    ollama_host: str | None = None,
    output_path: Path | None = None,
    source_file: str = "",
) -> Path:
    if output_path is None:
        output_path = build_output_path(output_dir)
    initialize_csv(output_path)
    model_label = f" (model: {model})" if model else ""
    host_label  = f" (host: {ollama_host})" if ollama_host else ""
    print(f"Results file initialized: {output_path}{model_label}{host_label}")

    total_items  = len(prompts)
    tests_run    = 0
    tests_passed = 0

    for index, item in enumerate(prompts, start=1):
        tests_run += 1
        if isinstance(item, dict):   # exchange
            passed = _run_exchange_item(
                item, index, total_items, output_path,
                model=model, ollama_host=ollama_host, source_file=source_file,
            )
            if passed:
                tests_passed += 1
        else:                        # plain string
            interrupted, passed = _run_single_item(
                str(item), index, total_items, output_path,
                model=model, ollama_host=ollama_host, source_file=source_file,
            )
            if passed:
                tests_passed += 1
            if interrupted:
                break

    print(f"\nResults written to: {output_path}")
    print(f"[TEST_SUMMARY] passed={tests_passed} total={tests_run}")
    return output_path


# ----------------------------------------------------------------------------------------------------
def _run_single_item(
    prompt: str,
    index: int,
    total_items: int,
    output_path: Path,
    model, ollama_host,
    source_file: str = "",
) -> tuple[bool, bool]:
    """Run a single standalone prompt.  Returns True if the run was interrupted."""
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{run_timestamp}] Running prompt {index}/{total_items}: {prompt!r}")

    row = _base_row(run_timestamp, source_file, prompt)
    try:
        duration, exit_code, stdout, stderr = invoke_framework(
            prompt, model=model, ollama_host=ollama_host,
        )
        log_file     = extract_log_file(stdout_text=stdout)
        final_output = extract_final_output(stdout_text=stdout)
        turn_metrics = _parse_turn_metrics(stdout)
        row.update({"final_output": final_output, "duration_seconds": f"{duration:.3f}",
                    "exit_code": exit_code, "log_file": log_file, "stderr": stderr.strip()})
    except subprocess.TimeoutExpired as e:
        row.update({"duration_seconds": f"{SUBPROCESS_TIMEOUT_SECONDS}.000",
                    "exit_code": 124, "stderr": f"Timeout: {e}"})
        turn_metrics = {}
    except KeyboardInterrupt:
        row.update({"exit_code": 130, "stderr": "Interrupted by user."})
        append_csv_row(output_path=output_path, row=row)
        status_label = "FAIL"
        print(f"  [{status_label}] duration={row['duration_seconds']}s  exit_code={row['exit_code']}")
        print("Interrupted by user, ending test run.")
        return True, False
    except Exception as e:
        row.update({"exit_code": 125, "stderr": f"Wrapper error: {e}"})
        turn_metrics = {}

    append_csv_row(output_path=output_path, row=row)
    for turn_idx, (prompt_tokens, tps_str) in sorted(turn_metrics.items()):
        print(f"[TURN {turn_idx}] tokens={prompt_tokens} tps={tps_str}")
    status_label = "OK" if row["exit_code"] == 0 else "FAIL"
    print(f"  [{status_label}] duration={row['duration_seconds']}s  exit_code={row['exit_code']}")
    return False, row["exit_code"] == 0


# ----------------------------------------------------------------------------------------------------
def _run_exchange_item(
    exchange: dict,
    index: int,
    total_items: int,
    output_path: Path,
    model, ollama_host,
    source_file: str = "",
) -> bool:
    """Run a multi-turn exchange.  Writes one CSV row per turn."""
    name   = exchange.get("exchange", f"exchange_{index}")
    turns  = exchange.get("turns", [])
    n      = len(turns)

    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{run_timestamp}] Running exchange {index}/{total_items}: {name!r} ({n} turn(s))")

    turn_prompts = [t["user"] for t in turns]

    try:
        duration, exit_code, stdout, stderr = invoke_exchange(
            turn_prompts, model=model, ollama_host=ollama_host,
        )
    except subprocess.TimeoutExpired as e:
        duration, exit_code = float(SUBPROCESS_TIMEOUT_SECONDS * n), 124
        stdout, stderr = "", f"Timeout: {e}"
    except Exception as e:
        duration, exit_code = 0.0, 125
        stdout, stderr = "", f"Wrapper error: {e}"

    log_file      = extract_log_file(stdout_text=stdout)
    turn_outputs  = _parse_turn_outputs(stdout)
    turn_metrics  = _parse_turn_metrics(stdout)
    per_turn_dur  = duration / n if n else duration
    any_assert_fail = False

    for turn_idx, turn in enumerate(turns, start=1):
        user_prompt  = turn["user"]
        assert_expr  = turn.get("assert", "")
        final_output = turn_outputs.get(turn_idx, "")
        assert_result = _evaluate_assert(assert_expr, final_output, exit_code)
        if assert_result == "FAIL":
            any_assert_fail = True

        row = _base_row(run_timestamp, source_file, user_prompt, exchange_name=name, turn_index=turn_idx)
        row.update({
            "final_output":     final_output,
            "assert_result":    assert_result,
            "duration_seconds": f"{per_turn_dur:.3f}",
            "exit_code":        exit_code,
            "log_file":         log_file,
            "stderr":           stderr.strip(),
        })
        append_csv_row(output_path=output_path, row=row)

        prompt_tokens, tps_str = turn_metrics.get(turn_idx, (0, "0"))
        print(f"[TURN {turn_idx}] tokens={prompt_tokens} tps={tps_str}")

        status_label = "OK" if exit_code == 0 else "FAIL"
        assert_label = f"  assert={assert_result}" if assert_expr else ""
        print(f"  [Turn {turn_idx}/{n}] [{status_label}]{assert_label}: {user_prompt!r}")

    return exit_code == 0 and not any_assert_fail


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="External test wrapper for MiniAgentFramework. "
                    "Invokes the framework as a subprocess and records results to CSV."
    )
    parser.add_argument(
        "--prompts-file",
        type=Path,
        required=True,
        help="Path to a JSON file containing an array of prompt strings or exchange objects.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Ollama model alias to pass to main.py (overrides its default).",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="Ollama host URL to pass to main.py (e.g. http://MONTBLANC:11434).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Exact output CSV path. Appends to the file if it already exists (header skipped).",
    )
    parser.add_argument(
        "--source-file",
        type=str,
        default="",
        help="Label written to the source_file column in the CSV (typically the prompts filename).",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: ENTRYPOINT
# ====================================================================================================
if __name__ == "__main__":
    args = parse_args()
    run_tests(
        prompts=load_prompts_file(args.prompts_file),
        output_dir=DEFAULT_OUTPUT_DIR,
        model=args.model,
        ollama_host=args.ollama_host,
        output_path=args.output_file,
        source_file=args.source_file or args.prompts_file.name,
    )
