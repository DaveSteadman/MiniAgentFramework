# MiniAgentFramework - Developer Notes

For user-facing setup and usage see [README.md](README.md).

---

## Module Breakdown

### 1) Orchestration runtime
- `code/main.py`
  - Main entrypoint; supports single-shot, chat, scheduler, and dashboard modes via `argparse`.
  - Runs iterative planning → execution → validation loop (up to `MAX_ITERATIONS` retries).
  - A single `threading.Lock` (`llm_lock`) is shared across all modes to serialise LLM calls.
  - Graceful shutdown uses `threading.Event` + SIGINT handler; sleeping loops wake every 0.5 s to check the event.

### 2) LLM + Ollama client layer
- `code/ollama_client.py`
  - Ollama health checks and auto-startup (`ensure_ollama_running`).
  - Model discovery and alias resolution (`list_ollama_models`, `resolve_model_name`). Short aliases like `"20b"` resolve to the first installed model whose tag contains that string.
  - LLM call with full token metrics (`call_ollama_extended`).
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
  - Dynamically imports only approved skill modules/functions - unknown names are rejected before any import is attempted.

### 5) Validation + logging
- `code/orchestration_validation.py`
  - Validates each iteration's skill usage, prompt completeness, and response quality.

- `code/runtime_logger.py`
  - Sectioned logger with large horizontal separators.
  - Writes evidence logs to `controldata/logs/run_YYYYMMDD_HHMMSS.txt`.
  - In chat mode verbose orchestration detail goes to the log file only; the console shows one compact status line per turn.

### 6) Skills catalog + concrete skills
- `code/skills_catalog_builder.py`
  - Scans `code/skills/**/skill.md`.
  - Generates `code/skills/skills_summary.md` as a single JSON payload used by the planner.

- `code/skills/DateTime/` - date and time skill functions.
- `code/skills/SystemInfo/` - runtime system info (Python version, Ollama version, RAM, disk, OS).
- `code/skills/FileAccess/` - sandboxed file read/write/list functions.
- `code/skills/Memory/`
  - Extracts and recalls durable environment facts via keyword relevance scoring.
  - Persists facts across runs in `code/skills/Memory/memory_store.txt`.
- `code/skills/WebSearch/` - searches the web via DuckDuckGo (no API key required), returning ranked results with title, URL, and snippet.
- `code/skills/WebExtract/` - fetches a URL and extracts its readable prose, stripping HTML markup, navigation, and ads, ready for LLM synthesis.

### 7) Scheduler
- `code/scheduler.py`
  - `load_schedules_dir(dir)` - globs all `*.json` files in the given directory, merges their `"tasks"` lists, and skips malformed files with a stderr warning.
  - `is_task_due(task, last_run, now)` - evaluates `"interval"` (minutes since last run) and `"daily"` (HH:MM wall clock) task types.
  - `llm_lock` - the module-level `threading.Lock` imported by all modes that call the LLM.

### 8) Terminal UI
- `code/ui/dashboard_app.py`
  - `DashboardApp` - 4-panel diff-based ANSI terminal UI running at 50 fps via `msvcrt.kbhit()`.
  - Panels: Ollama status bar (top), schedule timeline (left), tabbed log/chat area (right), chat input (bottom).
  - Three daemon threads: `_ollama_poll` (model status), `_log_tail` (log file), `_scheduler_loop` (scheduled tasks).

- `code/ui/widgets.py`
  - `ScrollLog`, `TextEdit`, `Label`, `TimelineWidget`.
  - `TimelineWidget` draws a minute-resolution timeline centred on the current time; `►` marks the current minute; task markers are derived from schedule definitions.

- `code/ui/screen.py` - diff-based ANSI renderer; only changed cells are re-emitted to the terminal.
- `code/ui/panel.py`, `code/ui/colors.py`, `code/ui/keys.py` - layout primitives, ANSI colour constants, key code definitions.

### 9) Test tooling
- `testcode/test_wrapper.py`
  - Invokes `code/main.py` as a subprocess for each prompt in a configurable test suite.
  - Records timing, exit code, final LLM output, and log file path to a timestamped CSV in `controldata/test_results/`.
  - Prompt suites are JSON files in `controldata/test_prompts/` and are loaded via `--prompts-file`.

- `testcode/test_analyzer.py`
  - Reads a test results CSV and parses each run's log file for structured diagnostics.
  - Classifies every prompt as `PASS`, `FAIL`, `TIMEOUT`, or `GAP` (capability gap admission).
  - Extracts: skills selected, planner mode (LLM vs fallback), iteration count, validation result.
  - Produces a `<name>_analysis.csv` and a `<name>_gaps.txt` gap report alongside the source CSV.
  - Invoked via `python code/main.py --analysetest <csv>` or directly as a CLI script.

### 10) Workspace path management
- `code/workspace_utils.py`
  - Single source of truth for all well-known directory paths. All modules import from here rather than constructing paths independently.
  - All accessors use `@lru_cache(maxsize=1)` - paths are computed once per process.

| Accessor | Path |
|---|---|
| `get_workspace_root()` | `<repo_root>/` |
| `get_controldata_dir()` | `<repo_root>/controldata/` |
| `get_logs_dir()` | `<repo_root>/controldata/logs/` |
| `get_schedules_dir()` | `<repo_root>/controldata/schedules/` |
| `get_test_prompts_dir()` | `<repo_root>/controldata/test_prompts/` |
| `get_test_results_dir()` | `<repo_root>/controldata/test_results/` |

---

## Project Flow (Single-Shot / Chat Turn)

1. Recall relevant memories and collect ambient system info.
2. Load `code/skills/skills_summary.md` and ask the planner LLM which skills to call (returns JSON).
3. Execute the approved Python skill calls in order and collect outputs.
4. Build the final enriched prompt from skill outputs, recalled memories, and the planner template.
5. Call the final LLM and validate the response.
6. Retry up to `MAX_ITERATIONS` times if validation fails, feeding back error context.
7. Log everything - planner prompt, plan JSON, skill outputs, final prompt, response, validation, and TPS for each LLM phase.

---

## Performance Metrics

Each LLM call (planner and final) reports completion token throughput in the log:

```
Planner TPS: 42.3 tok/s  (87 tokens)
Final LLM TPS: 38.1 tok/s  (142 tokens)
```

In chat mode TPS also appears in the per-turn console status line:

```
[Turn 1 | 1,204 / 32,768 ctx tokens (3.7%) | 42.3 tok/s | gemma3:20b]
```

These values come directly from Ollama's `eval_duration` field and reflect model generation speed only (prompt evaluation time is tracked separately).

---

## Folder Layout

```
code/                        Main Python source; all imports are relative to this directory.
  skills/                    One subdirectory per skill; each has skill.md + implementation.
  ui/                        Terminal UI components (dashboard only).
controldata/
  logs/                      Runtime evidence logs (run_YYYYMMDD_HHMMSS.txt).
  schedules/                 Schedule definition JSON files (*.json).
  test_prompts/              Prompt suite JSON files for the test wrapper.
  test_results/              CSV results and analysis files from test runs.
testcode/                    External test scripts (test_wrapper, test_analyzer, regressions).
data/                        Miscellaneous data files (e.g. systemstats.csv).
```
