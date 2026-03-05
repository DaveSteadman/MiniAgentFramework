# MiniAgentFramework

## Purpose
MiniAgentFramework is an orchestration experiment that blends LLM reasoning with Python tool execution.

The core idea is:
- let an LLM decide which Python skills to call,
- execute those skills safely in ordered steps,
- feed skill outputs back into the final LLM response.

This project uses a local Ollama runtime and focuses on transparent, logged orchestration flows.

## Major Elements

### 1) Orchestration runtime
- `code/main.py`
  - Main orchestration entrypoint.
  - Supports single-shot and interactive chat modes.
  - Runs iterative planning/execution/validation loop (up to `MAX_ITERATIONS` retries).
  - Produces timestamped execution logs in `logs/`.

### 2) LLM + Ollama client layer
- `code/ollama_client.py`
  - Ollama health checks and auto-startup (`ensure_ollama_running`).
  - Model discovery and alias resolution (`list_ollama_models`, `resolve_model_name`).
  - LLM call with full token metrics and TPS (`call_ollama_extended`).
  - `OllamaCallResult` carries `prompt_tokens`, `completion_tokens`, `eval_duration_ns`, and a computed `tokens_per_second` property.

### 3) Planning layer
- `code/planner_engine.py`
  - Builds planner prompts with the skills catalog as context.
  - Parses and validates planner JSON into typed execution plans.
  - Provides a deterministic DateTime fallback plan when the LLM response cannot be parsed.

- `code/preprocess_prompt.py`
  - Standalone CLI for generating and inspecting a skill execution plan without running the full pipeline.

### 4) Skill execution layer
- `code/skill_executor.py`
  - Executes allow-listed skill calls from the plan JSON.
  - Resolves `{placeholder}` arguments across sequential calls.
  - Dynamically imports only approved skill modules/functions.

### 5) Validation + logging
- `code/orchestration_validation.py`
  - Validates each iteration's skill usage, prompt completeness, and response quality.

- `code/runtime_logger.py`
  - Sectioned logger with large horizontal separators.
  - Writes evidence logs to `logs/run_YYYYMMDD_HHMMSS.txt`.
  - In chat mode, verbose orchestration detail goes to the log file only; the console shows one status line per turn.

### 6) Skills catalog + concrete skills
- `code/skills_catalog_builder.py`
  - Scans `code/skills/**/skill.md`.
  - Generates `code/skills/skills_summary.md` as a single JSON payload.

- `code/skills/DateTime/` — date and time skill functions.
- `code/skills/SystemInfo/` — runtime system info (Python version, Ollama version, RAM, disk, OS).
- `code/skills/FileAccess/` — sandboxed file read/write/list functions.
- `code/skills/Memory/`
  - Extracts and recalls durable environment facts via keyword relevance scoring.
  - Persists facts across runs in `code/skills/Memory/memory_store.txt`.
- `code/skills/WebSearch/` — searches the web via DuckDuckGo (no API key required), returning ranked results with title, URL, and snippet.
- `code/skills/WebExtract/` — fetches a URL and extracts its readable prose, stripping HTML markup, navigation, and ads, ready for LLM synthesis.

### 7) Test wrapper
- `testcode/test_wrapper.py`
  - Invokes `code/main.py` as a subprocess for each prompt in a configurable test suite.
  - Records timing, exit code, final LLM output, and log file path to a timestamped CSV.
  - Results land in `testcode/results/`.
  - Prompt suites are JSON files in `testcode/prompts/` and are loaded via `--prompts-file`.

### 8) Test analyzer
- `testcode/test_analyzer.py`
  - Reads a test results CSV and parses each run's log file for structured diagnostics.
  - Classifies every prompt as `PASS`, `FAIL`, `TIMEOUT`, or `GAP` (capability gap admission).
  - Extracts: skills selected, planner mode (LLM vs fallback), iteration count, validation result.
  - Produces a `<name>_analysis.csv` with per-prompt diagnostics and a `<name>_gaps.txt` gap report.
  - Invoked via `python code/main.py --analysetest <csv>` or directly as a CLI script.

## Project Flow (High Level)
1. Recall relevant memories and collect ambient system info.
2. Load `code/skills/skills_summary.md` and ask the planner LLM which skills to call.
3. Execute the approved Python skill calls in order and collect outputs.
4. Build the final enriched prompt from skill outputs, recalled memories, and the planner template.
5. Call the final LLM and validate the response.
6. Retry up to `MAX_ITERATIONS` times if validation fails, feeding back error context.
7. Log everything — planner prompt, plan JSON, skill outputs, final prompt, response, validation, and TPS for each LLM phase.

## Quick Start

### Prerequisites
- Python environment (project uses `.venv`).
- Ollama installed and available in `PATH`.
- At least one model pulled locally (e.g. `ollama pull gemma3:20b`).

### Activate the virtual environment
```powershell
.\.venv\Scripts\Activate.ps1
```

### Regenerate the skills catalog
Run this whenever a `skill.md` file is added or changed:
```powershell
python .\code\skills_catalog_builder.py
```

---

## Running: Single-Shot Mode

Runs one prompt through the full pipeline and exits.

```powershell
python .\code\main.py --user-prompt "what version of ollama is in use"
```

| Option | Default | Description |
|---|---|---|
| `--user-prompt TEXT` | `"output the time"` | The prompt to run. |
| `--model ALIAS` | `"20b"` | Ollama model alias or tag. Short aliases like `20b` are resolved to the first installed model whose tag contains that string. |
| `--num-ctx N` | `32768` | Context window size (tokens) passed to Ollama for both the planner and final LLM calls. |

**Example — specify model and context window:**
```powershell
python .\code\main.py --user-prompt "summarize system health" --model "20b" --num-ctx 16384
```

---

## Running: Chat Mode

Starts an interactive multi-turn REPL. Type `exit` or `quit` to end the session.

```powershell
python .\code\main.py --chat
```

Each turn runs the full orchestration pipeline. The console shows one compact status line per turn:

```
[Turn 1 | 1,204 / 32,768 ctx tokens (3.7%) | 42.3 tok/s | gemma3:20b]
```

Verbose orchestration detail (planner prompts, plan JSON, skill outputs, validation) is written to the log file only, keeping the console readable.

Conversation history is passed as context for each subsequent turn, capped at the last 10 turns to prevent context overflow.

| Option | Default | Description |
|---|---|---|
| `--chat` | off | Activates chat mode. |
| `--model ALIAS` | `"20b"` | Same alias resolution as single-shot mode. |
| `--num-ctx N` | `32768` | Context window for every turn in the session. |

**Example — chat with a smaller context window:**
```powershell
python .\code\main.py --chat --model "20b" --num-ctx 16384
```

---

## Running: Test Wrapper

Runs a suite of prompts through `code/main.py` as a subprocess and records results to a timestamped CSV.

```powershell
python .\testcode\test_wrapper.py
```

| Option | Default | Description |
|---|---|---|
| `--prompts TEXT [TEXT ...]` | — | One or more prompt strings (overrides `--prompts-file`). |
| `--prompts-file PATH` | `testcode/prompts/default_prompts.json` | JSON file containing an array of prompt strings. |
| `--output-dir PATH` | `testcode/results/` | Directory where the CSV results file is written. |

Each row in the CSV captures: `timestamp`, `prompt`, `final_output`, `duration_seconds`, `exit_code`, `log_file`, `stderr`.

**Example — run a named prompts file:**
```powershell
python .\testcode\test_wrapper.py --prompts-file testcode/prompts/test_web_skill_prompts.json
```

**Example — run a custom set of prompts inline:**
```powershell
python .\testcode\test_wrapper.py --prompts "output the time" "what is today's date" "how much RAM is available"
```

**Example — write results to a different directory:**
```powershell
python .\testcode\test_wrapper.py --output-dir .\data\test_runs
```

---

## Running: Test Analyzer

Analyzes a test results CSV without touching Ollama — reads each row's log file and classifies outcomes.

```powershell
python .\code\main.py --analysetest testcode\results\test_results_<timestamp>.csv
```

Or run the analyzer directly:
```powershell
python .\testcode\test_analyzer.py testcode\results\test_results_<timestamp>.csv
```

Produces two files alongside the source CSV:

| File | Contents |
|---|---|
| `<name>_analysis.csv` | Per-prompt row with: outcome, failure reason, skills selected, planner mode, iteration count, validation result. |
| `<name>_gaps.txt` | Summary report: pass rate, planner mode breakdown, iteration histogram, skill usage frequency, failing prompts, capability gap signals. |

Outcome labels:

| Label | Meaning |
|---|---|
| `PASS` | Exit 0, non-empty output, no failure signals detected. |
| `FAIL` | Non-zero exit code, empty output, or validation failure in log. |
| `TIMEOUT` | Subprocess exceeded the 300 s timeout (exit code 124). |
| `GAP` | Output contained a capability gap admission (e.g. "I cannot access the internet"). |

---

## Other Utilities

### Generate plan only (no execution)
Useful for inspecting what the planner would choose without running skills or the final LLM:
```powershell
python .\code\preprocess_prompt.py --user-prompt "output the time" --print-only
```

| Option | Default | Description |
|---|---|---|
| `--user-prompt TEXT` | *(required)* | Raw prompt to plan against. |
| `--model ALIAS` | `"gpt-oss:20b"` | Ollama model for the planner call. |
| `--num-ctx N` | `32768` | Context window for the planner call. |
| `--planner-ask TEXT` | built-in instruction | Override the planning instruction sent to the LLM. |
| `--output PATH` | `code/skills/skills_plan.json` | File path to write the plan JSON. |
| `--print-only` | off | Print plan JSON to stdout and skip writing the output file. |

### Monitor Ollama memory usage
Samples Ollama process RSS before and during model inference to characterise memory requirements:
```powershell
python .\code\system_check.py
python .\code\system_check.py --num-ctx 4096
```

| Option | Default | Description |
|---|---|---|
| `--num-ctx N` | none | Optional context window size to request during the test inference call. |

---

## Logging and Evidence
- Runtime evidence logs are written to `logs/run_YYYYMMDD_HHMMSS.txt`.
- Each log includes sectioned output for:
  - system status and resolved model,
  - memory store and recall,
  - ambient system info,
  - planner prompt and plan JSON (with planner TPS),
  - Python skill call outputs,
  - final prompt context,
  - final LLM response (with response TPS),
  - validation result per iteration.

## Performance Metrics
Each LLM call (planner and final) reports completion token throughput in the log:
```
Planner TPS: 42.3 tok/s  (87 tokens)
Final LLM TPS: 38.1 tok/s  (142 tokens)
```
In chat mode TPS also appears in the per-turn console status line. These values come directly from Ollama's `eval_duration` field and reflect model generation speed only (prompt evaluation time is recorded separately).
