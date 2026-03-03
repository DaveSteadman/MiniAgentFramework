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
  - Runs iterative planning/execution/validation loop.
  - Produces timestamped execution logs in `logs/`.

### 2) LLM + Ollama client layer
- `code/ollama_client.py`
  - Ollama health checks and startup (`ensure_ollama_running`).
  - Model discovery/resolution (`list_ollama_models`, `resolve_model_name`).
  - Prompt generation call (`call_ollama`).

### 3) Planning layer
- `code/planner_engine.py`
  - Builds planner prompts with skills context.
  - Parses/validates planner JSON into typed execution plans.
  - Provides deterministic fallback plan behavior.

- `code/preprocess_prompt.py`
  - CLI wrapper for generating structured skill execution plans.

### 4) Skill execution layer
- `code/skill_executor.py`
  - Executes allow-listed skill calls from plan JSON.
  - Resolves placeholder arguments between sequential calls.
  - Dynamically imports only approved skill modules/functions.

### 5) Validation + logging
- `code/orchestration_validation.py`
  - Validates each iteration output.

- `code/runtime_logger.py`
  - Sectioned logger with large horizontal separators.
  - Writes evidence logs to `logs/run_YYYYMMDD_HHMMSS.txt`.

### 6) Skills catalog + concrete skills
- `code/skills_catalog_builder.py`
  - Scans `code/skills/**/skill.md`.
  - Generates `code/skills/skills_summary.md` as a single JSON payload.

- `code/skills/DateTime/`
  - Date/time skill functions.

- `code/skills/SystemInfo/`
  - Runtime system info functions (including Python + Ollama versions).

## Project Flow (High Level)
1. Load `code/skills/skills_summary.md`.
2. Ask planner LLM which skills/functions to execute.
3. Validate and execute planned Python calls in order.
4. Build final prompt context with user question + skill outputs.
5. Ask final LLM for direct answer.
6. Validate outcome and log everything.

## Quick Start

### Prerequisites
- Python environment (project uses `.venv` in current setup).
- Ollama installed and available in PATH.
- Required model(s) pulled locally (for example `gpt-oss:20b`).

### Regenerate skills summary
```powershell
python .\code\skills_catalog_builder.py
```

### Run main orchestration
```powershell
python .\code\main.py --user-prompt "what version of ollama is in use" --num-ctx 32768
```

### Generate plan only (no execution)
```powershell
python .\code\preprocess_prompt.py --user-prompt "output the time" --print-only
```

### Monitor model/system memory usage
```powershell
python .\code\system_check.py --num-ctx 32768
```

## Logging and Evidence
- Runtime evidence logs are written to `logs/`.
- Each run includes sectioned output for:
  - system status,
  - preprocessing prompt,
  - plan JSON,
  - python call execution,
  - prompt context,
  - final LLM output,
  - validation status.

## Notes
- `code/hello_world_models.py` is retained as a compatibility wrapper that delegates to `code/main.py`.
- `code/build_skills_summary.py` is retained as a compatibility wrapper that delegates to `code/skills_catalog_builder.py`.
