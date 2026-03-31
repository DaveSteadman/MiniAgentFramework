# MiniAgentFramework - Developer Notes

![MiniAgentFramework](progress/readme_dev_header.png)

For user-facing setup and usage see [README.md](README.md).
For first-time setup see [README_GETTING_STARTED.md](README_GETTING_STARTED.md).

---

## Module Breakdown

### 1) Orchestration runtime
- `code/main.py`
  - Main entrypoint; starts the FastAPI server and Web UI.
  - Loads the skills catalog, resolves the model alias, configures the active Ollama host, and hands off to `modes/api_mode.py`.

- `code/chat_input.py`
  - Provides the persisted history store used by the API history endpoints.
  - Exposes `load_history()` and `append_to_history()` used by `api.py`.
  - History is stored in `controldata/chathistory.json` (max 32 entries, duplicates de-duped by full text match).

- `code/orchestration.py`
  - Core tool-calling loop called by `main.py` for every mode.
  - Builds the messages thread, calls the LLM, dispatches tool calls via `skill_executor`, and loops until the model returns a plain-text answer or `MAX_ITERATIONS` is exhausted.
  - **Context management constants:** `_TOOL_MSG_AUTO_SCRATCH_MIN = 600` (chars at which a tool result is auto-saved to the scratchpad) and `_TOOL_MSG_MAX_CHARS = 1500` (hard cap applied after the scratchpad save; excess is replaced with a pointer note).
  - **Context map:** every LLM round appends a `dict` entry to `_context_map` recording `round`, `label`, `chars`, `msg_idx` (index into `messages`), and `compacted` flag. The full map is printed to the log at the end of each run under a `[CONTEXT MAP]` section.
  - **Context budget logging:** before each LLM call the estimated thread size (chars and token estimate) plus remaining window headroom is logged; after each call the actual `prompt_tokens` from Ollama are logged.
  - **Auto-compaction:** before round N (N >= 3), any context-map entry from round <= N-2 whose `msg_idx` is not `None` is compacted via `compact_context()`, which replaces the message content in-place with a one-line headline and sets `compacted = True`.
  - **`_build_system_message(ambient_system_info, session_context, skills_payload)`** - module-level helper extracted from `orchestrate_prompt`. Assembles all runtime context sources (behavioural rules, ambient system info, prior-turn inject block, skill selection guidance, and scratchpad hints) into the single system message string sent on each round.
  - **`compact_context(context_map, messages, idx)`** - public helper; compacts a single context-map entry identified by list index; replaces the message content in-place with a one-line placeholder (referencing any auto-saved scratchpad key if present) and returns `True` on success.

- **`SessionContext`** - per-session cache of skill outputs for cross-turn and cross-task context injection.
  - Accumulates one entry per completed turn via `add_turn(user_prompt, assistant_response, skill_outputs)`.
  - On each subsequent turn, `as_inject_block()` returns a compact formatted digest of the last `MAX_INJECT_TURNS` (default 2) turns. This block is appended to the system prompt so the model can reference prior fetched data (web pages, code output, file content) without re-running the skills.
  - Each skill output is distilled to a compact summary by `_compact_output()`: search results become a list of `{url, title, snippet}` triplets (truncated to 50 words); page text and file content are capped at `MAX_CONTENT_WORDS` (300) words.
  - Optionally persisted: pass a `persist_path` to the constructor to save and reload state across process restarts. The file is a plain JSON object with a `"turns"` list. Scheduled tasks use this to carry state from a mining phase into an analysis phase even when the framework is restarted between runs.
  - **Cross-task injection**: three-phase tasks (mine -> analyze -> present) share one `SessionContext`. After Phase 1 writes mined files, Phase 2 receives the file paths via `as_inject_block()` without any explicit parameter wiring. The scheduler creates one `SessionContext` per task name and persists it under `controldata/chatsessions/<task_name>.json`.

- `code/slash_commands.py`
  - Registers and dispatches all `/` commands available in the Web UI chat input and scheduled-task prompts.
  - Each command is a plain function `_cmd_<name>(arg, ctx)` registered in `_REGISTRY` (handler map) and `_DESCRIPTIONS` (help text map).
  - `SlashCommandContext` dataclass carries the mutable runtime state (model, num_ctx, host, flags) plus an `output(text, style)` callback so handlers can write to the browser-facing runtime without depending on the transport.
  - **`/ctx` unified subcommand:** bare `/ctx` shows the context map and window size; `/ctx size [<n>]` reads or sets the window; `/ctx item <n>` prints the raw message content for a given map index; `/ctx compact <n>` compacts an entry in place and prints the before/after table.

### 2) LLM + Ollama client layer
- `code/ollama_client.py`
  - Supports local Ollama, LAN-hosted Ollama machines, and Ollama Cloud via `configure_host(host)`.
  - The active host is module-level state (same pattern as `_DEFAULT_LLM_TIMEOUT`); all public functions resolve to it automatically so no caller needs to pass a host.
  - `configure_host` is called from `main()` at startup using `--ollama-host` / `OLLAMA_HOST` env var.
  - `_is_local_host()` guards features that only make sense locally: `ensure_ollama_running` will not attempt to auto-start `ollama serve` for remote/cloud hosts. `get_ollama_ps_rows` calls `_get_ollama_ps_rows_local()` for local hosts (subprocess `ollama ps`) and `_get_ollama_ps_rows_remote()` for remote/cloud hosts (Ollama `/api/ps` HTTP endpoint).
  - Model discovery and alias resolution (`list_ollama_models`, `resolve_model_name`). Short aliases like `"20b"` resolve to the first installed model whose tag contains that string.
  - Primary LLM interface: `call_llm_chat` calls `/v1/chat/completions` with optional tool definitions and returns a `ChatCallResult` with token metrics and any tool call requests.
  - `call_ollama_extended` / `call_ollama` retain the legacy `/api/generate` path used by `skills_catalog_builder` and `system_check`.
  - `ChatCallResult` carries `message`, `finish_reason`, `prompt_tokens`, `completion_tokens`, and `tokens_per_second`.

### 3) Debug CLI tools
- `code/preprocess_prompt.py`
  - Standalone CLI that loads the skills catalog and prints the JSON Schema tool definitions sent to the model via `/v1/chat/completions`. Useful for debugging which functions are visible to the model and verifying that skill signatures are parsed correctly.

### 4) Skill execution layer
- `code/skill_executor.py`
  - Executes individual skill (tool) calls requested by the LLM tool-calling pipeline.
  - Resolves `{{token}}` placeholders in string arguments via `prompt_tokens.resolve_tokens`.
  - Dynamically imports only approved skill modules/functions - unknown names are rejected before any import is attempted.

### 5) Logging
- `code/runtime_logger.py`
  - Sectioned logger with large horizontal separators.
  - Writes evidence logs to `controldata/logs/YYYY-MM-DD/run_YYYYMMDD_HHMMSS.txt`.
  - Stores the full orchestration evidence used by the Web UI log panel and the test runner.

### 6) Skills catalog + concrete skills
- Each skill folder contains a `skill.md` definition file. When adding or editing a skill, follow the
  standard schema defined in [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md).

- `code/skills_catalog_builder.py`
  - Scans `code/skills/**/skill.md`.
  - Generates `code/skills/skills_summary.md` as a single JSON catalog.
  - `build_tool_definitions(skills_payload)` converts the catalog into JSON Schema tool definitions for the `/v1/chat/completions` API.
  - Rebuilt automatically (fast local path) at startup whenever any `skill.md` is newer than the summary; `/reskill` forces a full LLM-quality rebuild.

- `code/skills/DateTime/` - date and time skill functions.
- `code/skills/SystemInfo/` - runtime system info (Python version, Ollama version, RAM, disk, OS).
- `code/skills/FileAccess/` - sandboxed file read/write/list functions.
- `code/skills/Memory/`
  - Extracts and recalls durable environment facts via keyword relevance scoring.
  - Persists facts across runs in `code/skills/Memory/memory_store.json` (JSON, schema v2.0).
  - Auto-migrates legacy `memory_store.txt` on first run.
- `code/skills/WebSearch/` - searches the web via DuckDuckGo (no API key required), returning ranked results with title, URL, and snippet.
- `code/skills/TaskManagement/` - CRUD operations on scheduled task JSON files in `controldata/schedules/`. Exposes `list_tasks()`, `get_task(name)`, `create_task(name, schedule, prompt)`, `set_task_enabled(name, enabled)`, `set_task_schedule(name, schedule)`, `set_task_prompt(name, prompt)`, and `delete_task(name)` as skill functions the model can invoke from natural-language prompts. Each task is stored in its own `task_<name>.json` file; the API scheduler hot-reloads changes within its next poll cycle.
- `code/skills/Scratchpad/`
  - In-session key/value store backed by the module-level `_STORE` dict in `code/scratchpad.py`.
  - Does not persist to disk; lives only for the duration of the process.
  - Skill functions: `scratch_save(key, content)`, `scratch_load(key)`, `scratch_list()`, `scratch_delete(key)`, `scratch_search(substring)`, `scratch_peek(key, substring, context_chars=250)`.
  - `scratch_peek` returns a windowed excerpt around the first match of `substring` in the stored value for `key`, formatted as `[Match in 'key' at char N / M total]\n...prefix>>>match<<<suffix...`. Useful for large stored outputs where loading the full value would consume excessive context.
  - Auto-save: tool results >= 600 chars are automatically saved by `orchestration.py` under keys of the form `_tc_r<round>_<func_name>` so the model can retrieve them with `scratch_load` or inspect them with `scratch_peek`.

### 7) Scheduler
- `code/scheduler.py`
  - `load_schedules_dir(dir)` - globs all `*.json` files in the given directory, merges their `"tasks"` lists, and skips malformed files with a stderr warning.
  - `is_task_due(task, last_run, now)` - evaluates `"interval"` (minutes since last run) and `"daily"` (HH:MM wall clock) task types.
  - `TaskQueue.get_state(pending_limit=...)` - returns an internal queue snapshot used by the API layer to build the public queue DTO.
  - `llm_lock` - module-level alias for `task_queue.run_lock`; imported by all code paths that must serialise LLM access.

### 8) Web UI and API
- `code/api.py`
  - Defines the FastAPI app, REST endpoints, SSE endpoints, and static asset handlers for the browser UI.
  - `/queue` returns a minimal public DTO: `queued_prompt_count`, `next_prompts`, `next_prompts_limit`, and `updated_at`.
  - `/runs/{id}/stream` provides per-run SSE events; `/logs/stream` and `/logs/file` provide global and per-run log tailing.

- `code/modes/api_mode.py`
  - Starts uvicorn, publishes shared scheduler state into `api.py`, and runs the background scheduler thread.
  - On Windows it selects the selector event loop policy before starting uvicorn to avoid noisy Proactor disconnect callbacks under browser/SSE churn.

- `code/ui/index.html`, `code/ui/app.js`, `code/ui/style.css`
  - Static browser UI assets served directly by `api.py` with `Cache-Control: no-store`.
  - `app.js` drives queue polling, schedule timeline rendering, prompt submission, input history, and SSE run/log streams.
  - The queue subpanel shows a separate queued prompt total and the next prompts to be serviced.

### 9) Test tooling
- `testcode/test_wrapper.py`
  - Invokes `code/main.py` as a subprocess for each prompt in a configurable test suite.
  - Records timing, exit code, final LLM output, and log file path to a timestamped CSV in `controldata/test_results/`.
  - Prompt suites are JSON files in `controldata/test_prompts/` and are loaded via `--prompts-file`.
  - Accepts `--ollama-host` to run the full suite against a LAN or cloud Ollama host.
  - Invoked by the `/test` slash command; not intended for direct use.

- `testcode/test_analyzer.py`
  - Reads a test results CSV and parses each run's log file for structured diagnostics.
  - Classifies every prompt as `PASS`, `FAIL`, `TIMEOUT`, or `GAP` (capability gap admission).
  - Extracts: tools called (`skills_selected`), tool-calling mode (`TOOL_CALLS` / `DIRECT` / `UNKNOWN`), tool round count, validation result.
  - Produces a `<name>_analysis.csv` and a `<name>_gaps.txt` gap report alongside the source CSV.
  - Invoked directly as a CLI script.

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
| `get_chatsessions_dir()` | `<repo_root>/controldata/chatsessions/` |
| `get_chatsessions_day_dir()` | `<repo_root>/controldata/chatsessions/<YYYY-MM-DD>/` |

- `code/webpage_utils.py`
  - Shared HTTP fetching, HTML extraction, and text utilities used by web skill modules.
  - Skills import `fetch_html`, `extract_content`, and `truncate_to_words` from here rather than defining their own copies.
  - Uses BeautifulSoup when available and falls back to a pure-stdlib `html.parser` extractor automatically.

| Public symbol | Description |
|---|---|
| `HTTP_HEADERS` | Standard browser-impersonation request headers |
| `BS4_AVAILABLE` | `True` if `beautifulsoup4` is installed |
| `SKIP_TAGS`, `BLOCK_TAGS` | Frozensets controlling HTML element handling during extraction |
| `NOISE_HINTS` | Attribute substrings used to prune layout-noise containers |
| `MIN_PARA_WORDS` | Minimum words per extracted paragraph (below = boilerplate) |
| `fetch_html(url, timeout)` | Fetch a URL → `(html_text, final_url)` |
| `dedup_paragraphs(paragraphs)` | Remove near-duplicate paragraphs by first-80-char key |
| `extract_content(html_text)` | Extract `(page_title, body_text)` from raw HTML |
| `truncate_to_words(text, max_words)` | Trim body text to a word limit |

---

## Dependencies

All runtime dependencies are listed in [`requirements.txt`](requirements.txt).

| Package | Version | Required by | Notes |
|---|---|---|---|
| `beautifulsoup4` | >= 4.12 | WebFetch skill | Optional but strongly recommended. Falls back to stdlib `html.parser` if absent, but bs4 gives much cleaner extraction from real-world pages. |
| `psutil` | >= 5.9 | `system_check.py` | Provides RAM, disk, and CPU metrics. |
| `markdown` | >= 3.6 | WebResearchOutput skill | Optional; falls back to a minimal inline converter if absent. |
| `certifi` | >= 2024.0 | `webpage_utils.py` | Updated Mozilla CA bundle for SSL verification. |
| `fastapi` | >= 0.110 | `api.py` | REST API and browser UI server. |
| `uvicorn` | >= 0.29 | `modes/api_mode.py` | ASGI server used to host the FastAPI app. |

All other imports (`urllib`, `json`, `re`, `threading`, `pathlib`, …) are Python stdlib.

### Setup (new user)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Ollama and pull a model (external, one-time)
#    https://ollama.com - download the installer, then:
ollama pull gemma3:20b

# 4. Regenerate the skills catalog
python .\code\skills_catalog_builder.py
```

---

## Project Flow (Web UI Prompt / Scheduled Prompt)

The orchestration design is intentionally singular: one pipeline, one LLM, one native tool-calling loop. There is no separate planning stage, no separate finalisation stage, and no fixed number of steps. The model decides when it is done.

**Preparation (once per turn):**
1. Expand `{today}` / `{yesterday}` etc. in the prompt via `resolve_tokens`.
2. Run memory store and recall to build the system-prompt context block.
3. Collect ambient system info (OS, RAM, disk) to inject as static context.
4. Build JSON Schema tool definitions from `skills_summary.md` via `build_tool_definitions`.
5. Compose the system message and initial messages list.

**Tool-calling loop (repeating):**
6. Call `/v1/chat/completions` with the full messages thread and tool definitions.
7. If the model returns a plain-text response with no tool calls: that is the final answer - done.
8. If the model returns tool call requests: execute each one, append tool-role result messages, and go to step 6.
9. Repeat up to `MAX_ITERATIONS` rounds. The model exits naturally by answering directly; iterations are a safety cap, not a design step count.

**Safety net:**
10. If `MAX_ITERATIONS` rounds are exhausted without a plain-text answer, call the model one final time with tools disabled to force a synthesis response. This is a fallback for pathological loops, not expected behaviour.
11. As a last resort if the synthesis call returns empty content (can happen with thinking models that emit only internal tokens), `_build_fallback_answer` assembles a plain-text summary directly from the collected tool outputs so the user always sees something.

---

## Prompt Tokens

`code/prompt_tokens.py` provides date/time token resolution used throughout the framework.

| Token | Example output (today = 2026-03-11) |
|-------|--------------------------------------|
| `{today}` | `2026-03-11` |
| `{yesterday}` | `2026-03-10` |
| `{longdate}` | `March 11, 2026` |
| `{longdateyesterday}` | `March 10, 2026` |
| `{month_year}` | `March 2026` |
| `{month}` | `March` |
| `{year}` | `2026` |
| `{week}` | `10` |

Tokens are case-insensitive and resolved at call time, so scheduled prompts and stored queries stay perpetually current without manual edits.

**Two resolution passes happen on every turn:**

**Pass 1 - `orchestration.py`** (before the model sees the prompt):
```python
user_prompt = resolve_tokens(user_prompt)
```
A scheduled prompt like `"web mine UK news for {today}"` arrives at the model as `"web mine UK news for 2026-03-11"`. This is the primary pass for all user-facing and scheduled prompts.

**Pass 2 - `skill_executor.py`** (on each string argument in the LLM-generated skill call):
```python
resolved[key] = resolve_tokens(value)
```
By the time this runs, tokens are already resolved from Pass 1, so it is a no-op in the normal flow. This pass covers programmatic use - skill arguments constructed in code with `{today}` embedded are resolved here even when they bypass orchestration.

`parse_flexible_date(s)` (also in `prompt_tokens.py`) converts `"today"`, `"yesterday"`, or `"YYYY-MM-DD"` / `"YYYY/MM/DD"` to a `date` object; used by skills whose public API takes a human-readable date parameter.

---

## Performance Metrics

Each LLM call reports completion token throughput in the log:

```
Round 1 TPS: 42.3 tok/s  (87 tokens)
```

Token throughput is captured in the runtime logs and streamed into the Web UI log panel.

These values come directly from Ollama's `eval_duration` field and reflect model generation speed only (prompt evaluation time is tracked separately).

---

## Folder Layout

```
code/                        Main Python source; all imports are relative to this directory.
  skills/                    One subdirectory per skill; each has skill.md + implementation.
  ui/                        Browser UI static assets (index.html, app.js, style.css).
controldata/
  logs/YYYY-MM-DD/            Runtime evidence logs (run_YYYYMMDD_HHMMSS.txt) in dated subfolders.
  schedules/                 Schedule definition JSON files (*.json).
  test_prompts/              Prompt suite JSON files for the test wrapper.
  test_results/              CSV results and analysis files from test runs.
testcode/                    External test scripts (test_wrapper, test_analyzer, regressions).
data/                        Miscellaneous data files (e.g. systemstats.csv).
webresearch/
  01-Mine/                   Raw fetched content (URLs and search results as .md files).
  02-Analysis/               Processed and summarised research artefacts.
  03-Presentation/           Final polished outputs for sharing or reporting.
```

---

## Web Skills

Two web-facing skills are available. They compose naturally: search to discover URLs, then fetch
to read content, then `write_file` (FileAccess) to persist results.

### WebSearch

**Purpose:** Discover what is on the web. Returns title, URL, and snippet for the top N DuckDuckGo results. Nothing is saved to disk.

**Functions:** `search_web(query, max_results=5)`, `search_web_text(query, max_results=5)`

**Key behaviours:**
- Output lives only in the LLM context for the current turn.
- Chain with `fetch_page_text` (WebFetch) to read a result URL, and `write_file` (FileAccess) to persist output.

**Trigger prompts:**
- `search the web for <topic>`
- `find information about <topic>`
- `look up the latest news on <topic>`
- `what does the web say about <topic>`
- `do a web search for <query>`
- `search for recent articles on <topic>`
- `what is the current status of <topic>`

---

### WebFetch

**Purpose:** Fetch and read the content of a single, already-known URL. Strips HTML noise and returns clean prose, ready for the LLM to summarise or answer from.

**Function:** `fetch_page_text(url, max_words=1000, query=None)`

**Key behaviours:**
- Requires a full URL as input - it cannot discover URLs from a query.
- Set `query=` when looking for specific information - runs an isolated LLM extraction pass and returns only relevant facts, avoiding context overload from raw page text.
- Nothing is saved to disk. Chain with `write_file` to persist fetched content or `scratch_save` to hold it for later steps.

**Trigger prompts:**
- `fetch the page at <url>`
- `read the content of <url>`
- `get the article at <url>`
- `summarise the page at <url>`
- `what does this page say: <url>`
- `read this link and tell me about it: <url>`

---

## Known Ollama Hosts

The framework resolves the active Ollama host at startup via `ollama_client.configure_host()`.
Pass the host as a CLI argument or set the environment variable before launching.

```
python code/main.py --ollama-host http://MONTBLANC:11434
# or via env var:
set OLLAMA_HOST=http://MONTBLANC:11434
```

| Name | URL | Models | Notes |
|------|-----|--------|-------|
| Local | `http://localhost:11434` | *(locally installed)* | Default; `ollama serve` auto-started if not running |
| MONTBLANC (LAN) | `http://192.168.1.169:11434` | `qwen3-coder:480b-cloud`, `gpt-oss:20b` | LAN machine |
| Ollama Cloud | `https://api.ollama.com` | *(cloud catalogue)* | HTTPS endpoint; no local auto-start |

**Behaviour differences for non-local hosts:**
- `ensure_ollama_running` skips the auto-start attempt and raises a clean error if the host is unreachable.
- `get_ollama_ps_rows` calls the remote `/api/ps` HTTP endpoint for remote hosts, so the running-model list is available for LAN/cloud hosts too.
- All inference and model-listing calls work identically regardless of host.
