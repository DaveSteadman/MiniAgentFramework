# MiniAgentFramework - Developer Notes

![MiniAgentFramework](progress/readme_dev_header.png)

For user-facing setup and usage see [README.md](README.md).
For first-time setup see [README_GETTING_STARTED.md](README_GETTING_STARTED.md).
For design claims and SSE event contracts see [DESIGN.md](DESIGN.md).

---

## Code Layout

```
code/
  main.py
  agent_core/          - orchestration, LLM client, skills
  input_layer/         - API server, slash commands, chat history, browser UI
    ui/                - index.html, app.js, style.css
  scheduler/           - background task scheduler
  utils/               - logging, workspace helpers, version
```

---

## agent_core/

### main.py

- Entrypoint; resolves CLI args and `controldata/default.json` defaults, configures the Ollama host and model alias, loads the skills catalog, and starts the FastAPI server via `api_mode.py`.

### orchestration.py

- Core tool-calling loop for every prompt.
- Builds the messages thread, calls the LLM, dispatches tool calls via `skill_executor`, and loops until the model returns a plain-text response or `MAX_ITERATIONS` is exhausted.
- **Context map**: every LLM round appends an entry recording `round`, `label`, `chars`, `msg_idx`, and `compacted` flag. Printed to the log under `[CONTEXT MAP]` at run end.
- **Context management constants**: `_TOOL_MSG_AUTO_SCRATCH_MIN = 600` (chars at which a tool result is auto-saved to the scratchpad) and `_TOOL_MSG_MAX_CHARS = 1500` (hard cap after auto-save; excess replaced with a pointer note).
- **Auto-compaction**: before round N (N >= 3), any context-map entry from round <= N-2 is compacted via `compact_context()`, which replaces the message content with a one-line headline.
- **`_build_system_message(ambient_system_info, session_context, skills_payload)`**: assembles all runtime context sources (behavioural rules, system info, prior-turn inject block, skill guidance, scratchpad hints) into the system message sent on each round.
- **`compact_context(context_map, messages, idx)`**: public helper; compacts a single entry and returns `True` on success.
- **`SessionContext`**: per-session cache of skill outputs used for cross-turn context injection.
  - `add_turn(user_prompt, assistant_response, skill_outputs)` accumulates one entry per completed turn.
  - `as_inject_block()` returns a compact digest of the last `MAX_INJECT_TURNS` (default 2) turns, appended to the system prompt so the model can reference prior data without re-running skills.
  - Optionally persisted: pass `persist_path` to save and reload state across restarts. The scheduler creates one `SessionContext` per task name and persists it under `controldata/chatsessions/<task_name>.json`.

### ollama_client.py

- Supports local Ollama, LAN-hosted Ollama, and Ollama Cloud via `configure_host(host)`.
- `_is_local_host()` guards local-only features: `ensure_ollama_running` will not attempt to start `ollama serve` for remote or cloud hosts. `get_ollama_ps_rows` uses subprocess `ollama ps` locally and the `/api/ps` HTTP endpoint remotely.
- Model discovery and alias resolution: `list_ollama_models`, `resolve_model_name`. Short aliases like `"20b"` resolve to the first installed model whose tag contains that string.
- Primary LLM interface: `call_llm_chat` calls `/v1/chat/completions` with optional tool definitions and returns a `ChatCallResult` with token metrics and any tool call requests.
- `ChatCallResult` carries `message`, `finish_reason`, `prompt_tokens`, `completion_tokens`, and `tokens_per_second`.
- `call_ollama_extended` / `call_ollama` retain the legacy `/api/generate` path used by `skills_catalog_builder` and `system_check`.

### skill_executor.py

- Executes individual skill (tool) calls requested by the LLM.
- Resolves `{{token}}` placeholders in string arguments via `prompt_tokens.resolve_tokens`.
- Dynamically imports only approved skill modules/functions - unknown names are rejected before any import is attempted.

### skills_catalog_builder.py

- Scans `code/agent_core/skills/**/skill.md`.
- Generates `code/agent_core/skills/skills_summary.md` as a single JSON catalog.
- `build_tool_definitions(skills_payload)` converts the catalog into JSON Schema tool definitions for `/v1/chat/completions`.
- Rebuilt automatically at startup whenever any `skill.md` is newer than the summary. `/reskill` forces a full LLM-quality rebuild during an active session.

### scratchpad.py

- Module-level `_STORE` dict used by the Scratchpad skill for in-session key/value storage.
- Does not persist to disk; lives only for the duration of the process.

### inspect_tools.py

- Standalone CLI that loads the skills catalog and prints the JSON Schema tool definitions sent to the model via `/v1/chat/completions`. Useful for debugging which functions are visible to the model.

```powershell
python .\code\agent_core\inspect_tools.py
python .\code\agent_core\inspect_tools.py --output tool_definitions.json
```

### skills/

When adding or editing a skill, follow the schema in [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md).

| Skill folder | Description |
|---|---|
| `DateTime/` | Date and time functions. |
| `SystemInfo/` | Runtime system info: Python version, Ollama version, RAM, disk, OS. |
| `FileAccess/` | Sandboxed file read/write/list under the workspace. |
| `Memory/` | Extracts and recalls durable environment facts via keyword relevance scoring. Persists in `memory_store.json`. Auto-migrates legacy `memory_store.txt` on first run. |
| `WebSearch/` | Searches the web via DuckDuckGo - no API key required. Returns ranked results with title, URL, and snippet. |
| `WebFetch/` | Fetches and extracts readable prose from a URL. Optionally runs a focused LLM extraction pass when `query=` is supplied. |
| `WebNavigate/` | Extracts navigable hyperlinks from a page as a numbered list - sits between `WebSearch` (discovery) and `WebFetch` (reading). |
| `WebResearch/` | Multi-hop research traversal across search results and linked pages; returns a ranked evidence bundle. |
| `Wikipedia/` | Looks up a topic on Wikipedia and returns a plain-text article summary via the Wikipedia API. |
| `Kiwix/` | Searches and retrieves articles from a local Kiwix server (offline Wikipedia/Gutenberg snapshots). |
| `CodeExecute/` | Executes a self-contained Python stdlib snippet and returns captured stdout. |
| `Delegate/` | Creates a fresh child orchestration context for a focused sub-task; the child runs its own tool-calling loop and returns a compact answer to the parent. |
| `TaskManagement/` | CRUD operations on scheduled task JSON files in `controldata/schedules/`. |
| `Scratchpad/` | In-session key/value store. Skill functions include `scratch_save`, `scratch_load`, `scratch_list`, `scratch_delete`, `scratch_search`, and `scratch_peek`. `scratch_peek` returns a windowed excerpt around a match - useful for large stored values. |

---

## input_layer/

### api.py

- Defines the FastAPI app, all REST and SSE endpoints, and static asset handlers for the browser UI.
- **Session management**: `_session_path(session_id)` locates session files by checking `controldata/chatsessions/named/` first, then the root `chatsessions/` directory. Named sessions are stored as `session_{slug}.json`; ephemeral sessions as `{session_id}.json`.
- **`GET /completions`**: returns `{sessions, test_files, task_names, models}` used by the tab-completion dropdown in the browser UI.
- Key endpoints: `/queue` (DTO with queued count and next-prompt preview), `/runs/{id}/stream` (per-run SSE), `/logs/stream` (live log tail), `/history` (chat history for the UI), `/submit` (prompt submission), `/completions`.

### api_mode.py

- Starts uvicorn, publishes shared scheduler state into `api.py`, and runs the background scheduler thread.
- On Windows it selects the selector event loop policy before starting uvicorn to avoid noisy Proactor disconnect callbacks under browser and SSE churn.

### slash_commands.py

- Registers and dispatches all `/` commands available in the Web UI chat input and scheduled-task prompts.
- Each command is a plain function `_cmd_<name>(arg, ctx)` registered in `_REGISTRY` (handler map) and `_DESCRIPTIONS` (help text map).
- `SlashCommandContext` dataclass carries the mutable runtime state (model, num_ctx, host, flags, session_id) plus an `output(text, style)` callback so handlers can write to the browser-facing runtime without depending on the transport.
- Named session commands (`/session name|list|resume|resumecopy|park|delete|info`) are all handled in `_cmd_session`. `resumecopy` deep-copies a source session JSON to a new slug and then calls `switch_session`. `delete` uses exact case-insensitive name matching; deleting the active session automatically opens a fresh unnamed chat.
- New slash commands can be added by creating `_cmd_<name>(arg, ctx)` and registering it in `_REGISTRY` and `_DESCRIPTIONS`.

### chat_input.py

- Provides the persisted history store used by the API history endpoints.
- Exposes `load_history()` and `append_to_history()` used by `api.py`.
- History is stored in `controldata/chathistory.json` (max 32 entries, duplicates de-duped by full text match).

### ui/

- **`index.html`**: single-page shell; imports `app.js` and `style.css` with a cache-busting version query string.
- **`app.js`**: all browser-side logic including SSE event handling, tab completion, session switching, test streaming, and schedule timeline rendering. Tab completion state is driven by `_parseSuggestContext(value)` (three-tier: command name, sub-command, dynamic args from `/completions`) and rendered in the `#slash-suggest` dropdown positioned fixed above the chat input.
- **`style.css`**: dark theme using CSS custom properties (`--bg`, `--border`, `--accent`, etc.).

---

## scheduler/

### scheduler.py

- `load_schedules_dir(dir)`: globs all `*.json` files in the given directory, merges their `"tasks"` lists, and skips malformed files with a warning.
- `is_task_due(task, last_run, now)`: evaluates `"interval"` (minutes since last run) and `"daily"` (HH:MM wall clock) task types.
- `TaskQueue.get_state(pending_limit=...)`: returns a queue snapshot used by the API layer to build the public queue DTO.
- `llm_lock`: module-level alias for `task_queue.run_lock`; imported by all code paths that must serialise LLM access.

---

## utils/

### runtime_logger.py

- Sectioned logger with large horizontal separators.
- Writes evidence logs to `controldata/logs/YYYY-MM-DD/run_YYYYMMDD_HHMMSS.txt`.
- Stores the full orchestration evidence used by the Web UI log panel and the test runner.

### workspace_utils.py

- Path helpers for resolving all `controldata/` sub-directories: `get_controldata_dir()`, `get_chatsessions_dir()`, `get_chatsessions_named_dir()`, `get_schedules_dir()`, `get_logs_dir()`, etc.
- Used by `api.py`, `slash_commands.py`, and the scheduler to avoid hard-coded paths.

### system_check.py

- Samples Ollama process RSS before and during model inference to characterise memory requirements. Run directly as a CLI script.

```powershell
python .\code\utils\system_check.py
python .\code\utils\system_check.py --ctx 4096
```

### version.py

- Single source of truth for the framework version string shown by `/version` and in the UI header.

---

## controldata/

Runtime data and configuration written at run time. Not part of the source distribution - excluded from version control except for the schedule and test-prompt examples.

| Path | Contents |
|---|---|
| `default.json` | Persisted CLI defaults (model, ctx, agentport, ollamahost, kiwix_url). |
| `chathistory.json` | Input history for the chat panel (max 32 entries). |
| `memory_store.json` | Durable memory facts extracted by the Memory skill. |
| `chatsessions/` | Ephemeral session JSON files (one per session ID). |
| `chatsessions/named/` | Named session JSON files (`session_{slug}.json`). |
| `logs/YYYY-MM-DD/` | Run evidence logs, one file per orchestration run. |
| `schedules/task_*.json` | Scheduled task definitions. Hot-reloaded each scheduler cycle. |
| `test_prompts/` | Test suite JSON files run by the test wrapper. |
| `test_results/YYYY-MM-DD/` | CSV output from test runs. |

- `code/input_layer/ui/index.html`, `code/input_layer/ui/app.js`, `code/input_layer/ui/style.css`
  - Static browser UI assets served directly by `api.py` with `Cache-Control: no-store`.
  - `app.js` drives queue polling, schedule timeline rendering, prompt submission, input history, and SSE run/log streams.
  - The queue subpanel shows a separate queued prompt total and the next prompts to be serviced.
  - All UI assets use the project monospace font stack (`JetBrains Mono`, `Cascadia Code`, `Fira Code`) for a consistent terminal aesthetic.

### 9) Test tooling
- `code/testing/test_wrapper.py`
  - Invokes `code/main.py` as a subprocess for each prompt in a configurable test suite.
  - Records timing, exit code, final LLM output, and log file path to a timestamped CSV in `controldata/test_results/`.
  - Prompt suites are JSON files in `controldata/test_prompts/` and are loaded via `--prompts-file`.
  - Accepts `--ollamahost` to run the full suite against a LAN or cloud Ollama host.
  - Invoked by the `/test` slash command; not intended for direct use.

- `code/testing/test_analyzer.py`
  - Reads a test results CSV and parses each run's log file for structured diagnostics.
  - Classifies every prompt as `PASS`, `FAIL`, `TIMEOUT`, or `GAP` (capability gap admission).
  - Extracts: tools called (`skills_selected`), tool-calling mode (`TOOL_CALLS` / `DIRECT` / `UNKNOWN`), tool round count, validation result.
  - Produces a `<name>_analysis.csv` and a `<name>_gaps.txt` gap report alongside the source CSV.
  - Invoked directly as a CLI script.

### 10) Workspace path management
- `code/utils/workspace_utils.py`
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

- `code/utils/webpage_utils.py`
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
python .\code\agent_core\skills_catalog_builder.py
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

`code/agent_core/prompt_tokens.py` provides date/time token resolution used throughout the framework.

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
code/                            Main Python source; main.py is the entrypoint.
  agent_core/                    LLM orchestration, skill execution, and catalog.
    skills/                      One subdirectory per skill; each has skill.md + implementation.
    orchestration.py             Core tool-calling loop.
    skill_executor.py            Dispatches individual skill calls.
    skills_catalog_builder.py    Builds skills_summary.md from skill.md files.
    ollama_client.py             Ollama API client (local, LAN, cloud).
    scratchpad.py                In-session key/value store.
    prompt_tokens.py             Date/time token resolution.
    inspect_tools.py             Standalone CLI for debug tool definitions.
  input_layer/                   Web UI, API server, and chat input handling.
    api.py                       FastAPI app, REST and SSE endpoints.
    api_mode.py                  Uvicorn startup and background scheduler thread.
    chat_input.py                Persisted input history store.
    slash_commands.py            Slash command registry and handlers.
    ui/                          Browser UI static assets (index.html, app.js, style.css).
  scheduler/                     Task scheduling.
    scheduler.py                 Schedule loader, due-time evaluation, and TaskQueue.
  testing/                       Test scripts.
    test_wrapper.py              Invokes main.py per prompt; records CSV results.
    test_analyzer.py             Reads CSV results and classifies pass/fail.
  utils/                         Shared utilities.
    runtime_logger.py            Sectioned evidence logger.
    workspace_utils.py           Single source of truth for all well-known paths.
    webpage_utils.py             HTTP fetch, HTML extraction, and text utilities.
    system_check.py              Ollama memory usage sampler.
    version.py                   Framework version constant.
controldata/
  logs/YYYY-MM-DD/               Runtime evidence logs (run_YYYYMMDD_HHMMSS.txt) in dated subfolders.
  schedules/                     Schedule definition JSON files (*.json).
  test_prompts/                  Prompt suite JSON files for the test wrapper.
  test_results/                  CSV results and analysis files from test runs.
  chatsessions/                  Persisted SessionContext files for multi-phase scheduled tasks.
data/                            Miscellaneous data files used by skills during runs.
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
python code/main.py --ollamahost http://MONTBLANC:11434
# or via env var:
set OLLAMAHOST=http://MONTBLANC:11434
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
