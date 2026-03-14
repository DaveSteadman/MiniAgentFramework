# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# External test wrapper for MiniAgentFramework.
#
# Invokes the framework as a full system via subprocess (as a user would) and captures each
# prompt-response cycle with accurate timing. Results are written to a structured CSV file that
# uses proper quoting so that fields containing commas or newlines do not cause parsing errors.
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
#
# Usage:
#   python testcode/test_wrapper.py
#   python testcode/test_wrapper.py --output-dir controldata/test_results
#   python testcode/test_wrapper.py --prompts "output the time" "what is today's date"
#   python testcode/test_wrapper.py --prompts-file controldata/test_prompts/test_chat_exchanges.json
#   python testcode/test_wrapper.py --prompts-file controldata/test_prompts/default_prompts.json --ollama-host http://MONTBLANC:11434
#   python testcode/test_wrapper.py --prompts-file controldata/test_prompts/default_prompts.json --ollama-host https://api.ollama.com --ollama-api-key <key>
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
import tempfile
import time
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
REPO_ROOT            = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))
from workspace_utils import get_test_prompts_dir, get_test_results_dir  # noqa: E402

MAIN_SCRIPT          = REPO_ROOT / "code" / "main.py"
DEFAULT_OUTPUT_DIR   = get_test_results_dir()
DEFAULT_PROMPTS_FILE = get_test_prompts_dir() / "default_prompts.json"

DEFAULT_PROMPTS = None  # Loaded from DEFAULT_PROMPTS_FILE at runtime.

# Maximum time in seconds to wait for a single framework invocation before aborting.
SUBPROCESS_TIMEOUT_SECONDS = 300

CSV_FIELDS = ["timestamp", "prompt", "exchange_name", "turn_index",
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
    ollama_api_key: str | None = None,
) -> tuple[float, int, str, str]:
    """Invoke code/main.py with the given prompt and return (duration, exit_code, stdout, stderr)."""
    start_time = time.monotonic()

    cmd = [sys.executable, str(MAIN_SCRIPT), "--user-prompt", prompt]
    if model:
        cmd += ["--model", model]
    if ollama_host:
        cmd += ["--ollama-host", ollama_host]
    if ollama_api_key:
        cmd += ["--ollama-api-key", ollama_api_key]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    duration = time.monotonic() - start_time
    return duration, result.returncode, result.stdout, result.stderr


# ----------------------------------------------------------------------------------------------------
def invoke_exchange(
    turn_prompts: list[str],
    model: str | None = None,
    ollama_host: str | None = None,
    ollama_api_key: str | None = None,
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
        if ollama_api_key:
            cmd += ["--ollama-api-key", ollama_api_key]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
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


# ----------------------------------------------------------------------------------------------------
def _base_row(run_timestamp: str, prompt: str, exchange_name: str = "", turn_index: int = 0) -> dict:
    """Return a pre-populated CSV row dict with all fields at safe defaults."""
    return {
        "timestamp":        run_timestamp,
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
    ollama_api_key: str | None = None,
) -> Path:
    output_path = build_output_path(output_dir)
    initialize_csv(output_path)
    model_label = f" (model: {model})" if model else ""
    host_label  = f" (host: {ollama_host})" if ollama_host else ""
    print(f"Results file initialized: {output_path}{model_label}{host_label}")

    total_items = len(prompts)

    for index, item in enumerate(prompts, start=1):
        if isinstance(item, dict):   # exchange
            _run_exchange_item(
                item, index, total_items, output_path,
                model=model, ollama_host=ollama_host, ollama_api_key=ollama_api_key,
            )
        else:                        # plain string
            interrupted = _run_single_item(
                str(item), index, total_items, output_path,
                model=model, ollama_host=ollama_host, ollama_api_key=ollama_api_key,
            )
            if interrupted:
                break

    print(f"\nResults written to: {output_path}")
    return output_path


# ----------------------------------------------------------------------------------------------------
def _run_single_item(
    prompt: str,
    index: int,
    total_items: int,
    output_path: Path,
    model, ollama_host, ollama_api_key,
) -> bool:
    """Run a single standalone prompt.  Returns True if the run was interrupted."""
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{run_timestamp}] Running prompt {index}/{total_items}: {prompt!r}")

    row = _base_row(run_timestamp, prompt)
    try:
        duration, exit_code, stdout, stderr = invoke_framework(
            prompt, model=model, ollama_host=ollama_host, ollama_api_key=ollama_api_key,
        )
        log_file     = extract_log_file(stdout_text=stdout)
        final_output = extract_final_output(stdout_text=stdout, stderr_text=stderr, log_file=log_file)
        row.update({"final_output": final_output, "duration_seconds": f"{duration:.3f}",
                    "exit_code": exit_code, "log_file": log_file, "stderr": stderr.strip()})
    except subprocess.TimeoutExpired as e:
        row.update({"duration_seconds": f"{SUBPROCESS_TIMEOUT_SECONDS}.000",
                    "exit_code": 124, "stderr": f"Timeout: {e}"})
    except KeyboardInterrupt:
        row.update({"exit_code": 130, "stderr": "Interrupted by user."})
        append_csv_row(output_path=output_path, row=row)
        status_label = "FAIL"
        print(f"  [{status_label}] duration={row['duration_seconds']}s  exit_code={row['exit_code']}")
        print("Interrupted by user, ending test run.")
        return True
    except Exception as e:
        row.update({"exit_code": 125, "stderr": f"Wrapper error: {e}"})

    append_csv_row(output_path=output_path, row=row)
    status_label = "OK" if row["exit_code"] == 0 else "FAIL"
    print(f"  [{status_label}] duration={row['duration_seconds']}s  exit_code={row['exit_code']}")
    return False


# ----------------------------------------------------------------------------------------------------
def _run_exchange_item(
    exchange: dict,
    index: int,
    total_items: int,
    output_path: Path,
    model, ollama_host, ollama_api_key,
) -> None:
    """Run a multi-turn exchange.  Writes one CSV row per turn."""
    name   = exchange.get("exchange", f"exchange_{index}")
    turns  = exchange.get("turns", [])
    n      = len(turns)

    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{run_timestamp}] Running exchange {index}/{total_items}: {name!r} ({n} turn(s))")

    turn_prompts = [t["user"] for t in turns]

    try:
        duration, exit_code, stdout, stderr = invoke_exchange(
            turn_prompts, model=model, ollama_host=ollama_host, ollama_api_key=ollama_api_key,
        )
    except subprocess.TimeoutExpired as e:
        duration, exit_code = float(SUBPROCESS_TIMEOUT_SECONDS * n), 124
        stdout, stderr = "", f"Timeout: {e}"
    except Exception as e:
        duration, exit_code = 0.0, 125
        stdout, stderr = "", f"Wrapper error: {e}"

    log_file      = extract_log_file(stdout_text=stdout)
    turn_outputs  = _parse_turn_outputs(stdout)
    per_turn_dur  = duration / n if n else duration

    for turn_idx, turn in enumerate(turns, start=1):
        user_prompt  = turn["user"]
        assert_expr  = turn.get("assert", "")
        final_output = turn_outputs.get(turn_idx, "")
        assert_result = _evaluate_assert(assert_expr, final_output, exit_code)

        row = _base_row(run_timestamp, user_prompt, exchange_name=name, turn_index=turn_idx)
        row.update({
            "final_output":     final_output,
            "assert_result":    assert_result,
            "duration_seconds": f"{per_turn_dur:.3f}",
            "exit_code":        exit_code,
            "log_file":         log_file,
            "stderr":           stderr.strip(),
        })
        append_csv_row(output_path=output_path, row=row)

        status_label = "OK" if exit_code == 0 else "FAIL"
        assert_label = f"  assert={assert_result}" if assert_expr else ""
        print(f"  [Turn {turn_idx}/{n}] [{status_label}]{assert_label}: {user_prompt!r}")


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
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="Ollama host URL to pass to main.py (e.g. http://MONTBLANC:11434).",
    )
    parser.add_argument(
        "--ollama-api-key",
        type=str,
        default=None,
        help="Ollama API key to pass to main.py (for Ollama Cloud).",
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

    run_tests(
        prompts=prompts,
        output_dir=args.output_dir,
        model=args.model,
        ollama_host=args.ollama_host,
        ollama_api_key=args.ollama_api_key,
    )
