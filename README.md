# MiniAgentFramework

## Purpose
MiniAgentFramework is an orchestration experiment that blends LLM reasoning with Python tool execution.

The core idea is:
- let an LLM decide which Python skills to call,
- execute those skills safely in ordered steps,
- feed skill outputs back into the final LLM response.

This project uses a local Ollama runtime and focuses on transparent, logged orchestration flows.

> For module architecture, internal design, and project flow details see [README_DEVS.md](README_DEVS.md).

---

## Modes of Operation

| Mode | Purpose | Typical command |
|---|---|---|
| **User Prompt** | Run one prompt through the full pipeline and exit | `python .\code\main.py --user-prompt "what time is it"` |
| **Chat** | Interactive multi-turn REPL | `python .\code\main.py --chat` |
| **Scheduler** | Run scheduled prompt tasks from `controldata/schedules/` unattended | `python .\code\main.py --scheduler` |
| **Scheduled Item** | Run one named scheduled task immediately (debugging aid) | `python .\code\main.py --scheduled-item <name>` |
| **Dashboard** | Full terminal UI: schedule timeline, live log tail, and chat combined | `python .\code\main.py --dashboard` |
| **Test Wrapper** | Run a prompt suite as subprocesses and capture results to a CSV | `python .\testcode\test_wrapper.py` |
| **Test Analyzer** | Classify outcomes and produce diagnostics from a test results CSV | `python .\code\main.py --analysetest <csv>` |

---

## Quick Start

### Prerequisites
- Python 3.11+ with a virtual environment (project uses `.venv`).
- Ollama installed and available in `PATH` - [https://ollama.com](https://ollama.com).
- At least one model pulled locally (e.g. `ollama pull gemma3:20b`).

### First-time setup
```powershell
# Create and activate the virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install -r requirements.txt

# Regenerate the skills catalog
python .\code\skills_catalog_builder.py
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
| `--ollama-host URL` | `http://localhost:11434` | Ollama host to use. Accepts a LAN address (e.g. `http://MONTBLANC:11434`) or `https://api.ollama.com`. Falls back to `OLLAMA_HOST` env var. |
| `--ollama-api-key KEY` | *(none)* | API key for authenticated hosts (Ollama Cloud). Falls back to `OLLAMA_API_KEY` env var. Applies to all modes. |

**Example - specify model and context window:**
```powershell
python .\code\main.py --user-prompt "summarize system health" --model "20b" --num-ctx 16384
python .\code\main.py --user-prompt "write the system information to a data/systemstats.csv spreadsheet" --model "gpt-oss:120b" --num-ctx 32768
python .\code\main.py --user-prompt "write a spreadsheet of numbers to data/sequencenumbers.csv where the first column is the index, then an incrementing prime number, then an incrementing fibonacci number" --model "gpt-oss:120b" --num-ctx 32768
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

In console chat mode the prompt supports persistent keyboard history (up/down arrows) backed by `controldata/chathistory.json`, shared across all sessions.

Slash commands (see [Slash Commands](#slash-commands) below) are available at the prompt to change model or context size without restarting.

| Option | Default | Description |
|---|---|---|
| `--chat` | off | Activates chat mode. |
| `--model ALIAS` | `"20b"` | Same alias resolution as single-shot mode. |
| `--num-ctx N` | `32768` | Context window for every turn in the session. |

**Example - chat with a smaller context window:**
```powershell
python .\code\main.py --chat --model "20b" --num-ctx 16384
```

---

## Running: Schedule Item Mode

Runs a single named task from the schedule files immediately, bypassing its normal schedule. Useful for debugging a task definition without waiting for its configured time or interval. The `enabled` flag is ignored so disabled tasks can be exercised too.

```powershell
python .\code\main.py --scheduled-item <name>
```

Loads all `*.json` files under `controldata/schedules/`, finds the first task whose `name` matches the supplied value, and runs its full prompt sequence in order.

| Option | Default | Description |
|---|---|---|
| `--scheduled-item NAME` | *(required)* | Name of the task to run. |
| `--model ALIAS` | `"20b"` | Ollama model alias or tag. |
| `--num-ctx N` | `32768` | Context window size. |

**Example:**
```powershell
python .\code\main.py --scheduled-item SystemHealth
python .\code\main.py --scheduled-item morning_web_scan --model "8b"
```

---

## Running: Scheduler Mode

Runs scheduled prompt tasks from `controldata/schedules/` as a background loop. Each `*.json` file in that directory can define one or more tasks with either a daily time (`HH:MM`) or a repeating interval (minutes). Tasks fire unattended and are serialised through the same LLM lock used by all other modes.

```powershell
python .\code\main.py --scheduler
```

Press **Ctrl+C** for a clean shutdown - in-flight LLM calls are allowed to complete before exit.

Schedule files live in `controldata/schedules/`. Each file must contain a top-level `"tasks"` list:

```json
{
  "tasks": [
    { "name": "system_health_check", "enabled": true, "type": "interval", "interval_minutes": 60, "prompt": "summarize system health" },
    { "name": "morning_web_scan",     "enabled": true, "type": "daily",    "time": "05:00",          "prompt": "summarise tech news" }
  ]
}
```

| Option | Default | Description |
|---|---|---|
| `--model ALIAS` | `"20b"` | Ollama model used for all scheduled task calls. |
| `--num-ctx N` | `32768` | Context window for scheduled task calls. |

---

## Running: Dashboard Mode

Combines the schedule timeline, live log tail, and chat interface in a single terminal UI. Three panels are always visible: the Ollama status bar at the top, a scrolling schedule timeline on the left, and a tabbed main area (Log / Chat) on the right.

```powershell
python .\code\main.py --dashboard
```

![Dashboard screenshot](progress/2026-03-07-UI.png)

| Key | Action |
|---|---|
| **Tab** | Switch between Log and Chat tabs |
| **Enter** | Submit chat prompt (Chat tab) |
| **↑ / ↓ / PgUp / PgDn** | Scroll the active panel |
| **Ctrl+C** | Clean shutdown |

Slash commands (see [Slash Commands](#slash-commands) below) are available in the Chat input bar to change model or context size at runtime.

| Option | Default | Description |
|---|---|---|
| `--model ALIAS` | `"20b"` | Model used for chat prompts in the dashboard. |
| `--num-ctx N` | `32768` | Context window for dashboard chat calls. |


---

## Slash Commands

Slash commands are available in **Chat mode** (console), the **Dashboard** chat input bar, and inside **scheduled task prompt lists**. They bypass the orchestration pipeline and take effect immediately.

Type `/help` at any prompt to see the full list. Current commands:

| Command | Description |
|---|---|
| `/help` | List all available slash commands |
| `/exit` | Exit dashboard mode |
| `/models` | List installed Ollama models; the active model is marked with `►` |
| `/model <name>` | Switch the active model for all subsequent runs (e.g. `/model 8b`). Accepts the same short aliases as `--model`. Clears conversation history. |
| `/host <target> [api-key]` | Switch the active Ollama host without restarting. Clears conversation history. See [Host targeting](#host-targeting) below. |
| `/ctx <tokens>` | Set the context window size for all subsequent runs (e.g. `/ctx 16384`). Accepts integers with optional commas or underscores. |
| `/timeout <seconds>` | Set the LLM generation timeout (e.g. `/timeout 1800` for heavy analysis tasks). |
| `/stopmodel [name]` | Unload a running model from VRAM. Defaults to the active model if no name given. |
| `/clearmemory` | Delete the memory store file (`memory_store.json`), starting the next session with a blank memory. |
| `/reskill` | Rebuild the skills catalog from `skill.md` files and hot-reload into the current session. |
| `/finalgen <on\|off>` | Control the final LLM synthesis call. `off` returns skill output directly (useful for web mining or data-collection steps). Bare `/finalgen` shows the current state. |
| `/sandbox <on\|off>` | Toggle the Python sandbox for `CodeExecute` skill. `on` (default) enforces the built-in allow-list; `off` removes restrictions (use with care). |
| `/deletelogs <days>` | Delete log date-folders under `controldata/logs/` older than N days. Each folder is named `YYYY-MM-DD` and contains all runs from that day. Useful as a scheduled task prompt (e.g. `/deletelogs 10`). |
| `/test <prompts-file>` | Run the test wrapper against a prompts file from `controldata/test_prompts/` and stream results live. The current host and model are forwarded automatically. Omit the argument to list available files. |

### Host targeting

`/host` accepts several forms, all equivalent in meaning:

| Input | Resolves to |
|---|---|
| `/host local` | `http://localhost:11434` |
| `/host MONTBLANC` | `http://MONTBLANC:11434` |
| `/host 192.168.1.169` | `http://192.168.1.169:11434` |
| `/host http://192.168.1.169:11434` | `http://192.168.1.169:11434` (unchanged) |
| `/host https://api.ollama.com myapikey` | `https://api.ollama.com` with API key |

Any bare hostname or IP address (no `://`) is automatically wrapped as `http://<name>:11434` — the standard Ollama default port. Full URLs are passed through unchanged, so custom ports and HTTPS cloud endpoints work too.

New slash commands can be added in [code/slash_commands.py](code/slash_commands.py) by adding a handler function and registering it in `_REGISTRY` and `_DESCRIPTIONS`.

---

## Running: Test Wrapper

Runs a suite of prompts through `code/main.py` as a subprocess and records results to a timestamped CSV.

```powershell
python .\testcode\test_wrapper.py
```

| Option | Default | Description |
|---|---|---|
| `--prompts TEXT [TEXT ...]` | - | One or more prompt strings (overrides `--prompts-file`). |
| `--prompts-file PATH` | `controldata/test_prompts/default_prompts.json` | JSON file containing an array of prompt strings. |
| `--output-dir PATH` | `controldata/test_results/` | Directory where the CSV results file is written. |
| `--model ALIAS` | `"20b"` | Ollama model alias passed to each `main.py` subprocess invocation. |
| `--ollama-host URL` | *(local)* | Ollama host for all subprocess invocations (e.g. `http://MONTBLANC:11434`). |
| `--ollama-api-key KEY` | *(none)* | API key forwarded to each subprocess invocation. |

Each row in the CSV captures: `timestamp`, `prompt`, `final_output`, `duration_seconds`, `exit_code`, `log_file`, `stderr`.

**Example - run a named prompts file:**
```powershell
python .\testcode\test_wrapper.py --prompts-file controldata/test_prompts/test_web_skill_prompts.json
```

**Example - run a custom set of prompts inline:**
```powershell
python .\testcode\test_wrapper.py --prompts "output the time" "what is today's date" "how much RAM is available"
```

---

## Running: Test Analyzer

Analyzes a test results CSV without touching Ollama - reads each row's log file and classifies outcomes.

```powershell
python .\code\main.py --analysetest controldata\test_results\test_results_<timestamp>.csv
```

Or run the analyzer directly:
```powershell
python .\testcode\test_analyzer.py controldata\test_results\test_results_<timestamp>.csv
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

## Logs and Output

| Path | Contents |
|---|---|
| `controldata/logs/YYYY-MM-DD/` | Runtime evidence logs (`run_YYYYMMDD_HHMMSS.txt`) — one file per run, grouped into dated subfolders. |
| `controldata/schedules/` | Schedule definition files (`*.json`) consumed by Scheduler and Dashboard modes. |
| `controldata/test_prompts/` | Prompt suite JSON files used by the Test Wrapper. |
| `controldata/test_results/` | Timestamped CSV results and analysis files produced by the Test Wrapper and Analyzer. |

Each log file contains full evidence for its run: resolved model, memory recall, skill outputs, planner JSON, final prompt, LLM response, and per-call token throughput.
