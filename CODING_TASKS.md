## Coding tasks
- First we need some basic architectural python files to call the LLM (Ollama) with a model name and a prompt, recieving the returned string
    - Lets test this, calling 20b and 120b models with a hello world

## Progress
- Added `ollama_client.py` with `call_ollama(model_name, prompt, host)` to return the generated response string.
- Added `hello_world_models.py` to test calls against `20b` and `120b` using prompt `hello world`.
- Executed the test script; Python call flow works, but local Ollama reports both models are missing (`404 model not found`).
- We have a basic orchestrator running. Pleased with that! Now to build on the robustness and completeness of it.

## Next step
- Pull or tag local models named `20b` and `120b` (or update `MODELS` in `hello_world_models.py` to installed model names), then rerun:
    - `C:/Users/daves/AppData/Local/Python/pythoncore-3.14-64/python.exe hello_world_models.py`

## Added monitoring
- Added `system_check.py` to sample memory usage while each model call runs.
- Reports per model:
    - Ollama process RSS baseline / peak / delta (GB)
    - System RAM baseline / peak / delta (GB)
- Run with:
    - `python .\\code\\system_check.py`

## Preflight and error fixes
- Added Ollama preflight utilities in `ollama_client.py`:
    - `is_ollama_running()`
    - `start_ollama_server()`
    - `ensure_ollama_running()`
    - `list_ollama_models()`
    - `resolve_model_name()`
- `hello_world_models.py` now checks server/model availability first and maps `20b`/`120b` to installed tags (for example `gpt-oss:20b`, `gpt-oss:120b`).
- `system_check.py` now uses the same preflight/mapping logic before sampling memory.