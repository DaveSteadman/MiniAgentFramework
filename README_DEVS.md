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
- `code/skills/WebResearch/` - mines URLs or DuckDuckGo searches into persisted Markdown files in the `webresearch/01-Mine/` workspace. Supports inline article content embedding via `fetch_content=True`.
- `code/skills/PageAssess/` - fetches a URL, classifies it as `article`, `index`, or `mixed` using text-density heuristics, and returns article-candidate links filtered by topic. No files written.

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

- `code/webresearch_utils.py`
  - Three-stage web research workspace under `webresearch/`.
  - Manages `01-Mine`, `02-Analysis`, and `03-Presentation` stage directories, each partitioned by domain and `yyyy/mm/dd/NNN-slug` dated folders.

| Accessor | Path |
|---|---|
| `get_webresearch_root()` | `<repo_root>/webresearch/` |
| `get_stage_dir(stage)` | `<repo_root>/webresearch/<stage>/` |
| `get_domain_dir(stage, domain)` | `<repo_root>/webresearch/<stage>/<domain>/` |
| `get_date_dir(stage, domain)` | `<repo_root>/webresearch/<stage>/<domain>/yyyy/mm/dd/` |
| `create_item_dir(stage, domain, slug)` | Creates and returns `NNN-slug/` inside the date dir |

- `code/webpage_utils.py`
  - Shared HTTP fetching, HTML extraction, and text utilities used by all four web skill modules (WebExtract, WebResearch, PageAssess, WebSearch).
  - Centralises ~200 lines of previously duplicated code; skills import `fetch_html`, `extract_content`, and `truncate_to_words` from here rather than defining their own copies.
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
| `beautifulsoup4` | ≥ 4.12 | WebExtract, WebResearch skills | Optional but strongly recommended — both skills fall back to stdlib `html.parser` if absent, but bs4 gives much cleaner extraction from real-world pages. |
| `psutil` | ≥ 5.9 | `system_check.py` | Provides RAM, disk, and CPU metrics. |

All other imports (`urllib`, `json`, `re`, `threading`, `pathlib`, …) are Python stdlib.

### Setup (new user)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Ollama and pull a model (external, one-time)
#    https://ollama.com — download the installer, then:
ollama pull gemma3:20b

# 4. Regenerate the skills catalog
python .\code\skills_catalog_builder.py
```

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
webresearch/
  01-Mine/                   Raw fetched content (URLs and search results as .md files).
  02-Analysis/               Processed and summarised research artefacts.
  03-Presentation/           Final polished outputs for sharing or reporting.
  (each stage uses <domain>/yyyy/mm/dd/NNN-slug/ sub-directories)
```

---

## Web Skills: WebSearch vs WebExtract vs WebResearch vs PageAssess

There are four web-facing skills. They are deliberately narrow in scope so the planner can
compose them correctly. Each serves a different stage in the "find → assess → read → keep" pipeline.

### Overview

| | WebSearch | WebExtract | WebResearch | PageAssess |
|---|---|---|---|---|
| **What it does** | Returns a ranked list of URLs + snippets from DuckDuckGo | Fetches one URL and returns its readable prose | Mines a URL or search into a persisted Markdown file | Classifies a URL as article/index/mixed; returns filtered links |
| **Input** | A query string | A URL | A URL or query string, plus a domain label | A URL, optional topic, optional link cap |
| **Output** | Structured result list (in-memory / LLM context) | Plain text (in-memory / LLM context) | A saved `.md` file on disk; returns the file path | A structured dict (in-memory / LLM context) |
| **Persists anything?** | No | No | Yes — writes to `webresearch/01-Mine/` | No |
| **Needs a domain label?** | No | No | Yes (e.g. `"CarIndustry"`, `"GeneralNews"`) | No |
| **Typical use** | Discovery — find candidate URLs | Deep-read — get the content of one known URL | Research archiving — save raw material for later analysis | Pre-qualification — decide whether a URL is worth mining |

---

### WebSearch

**Purpose:** Discover what is on the web. Returns title, URL, and snippet for the top N DuckDuckGo results. Nothing is saved.

**Key behaviours:**
- Output lives only in the LLM context for the current turn.
- Commonly used as the first step in a two-step chain: search → then WebExtract one or more of the resulting URLs.
- Does *not* save results to disk; if persistence is required, use WebResearch (`mine_search`) instead.

**Trigger prompts:**
- `search the web for <topic>`
- `find information about <topic>`
- `look up the latest news on <topic>`
- `what does the web say about <topic>`
- `find me some links about <topic>`
- `do a web search for <query>`
- `search for recent articles on <topic>`
- `what is the current status of <topic>`

---

### WebExtract

**Purpose:** Read the content of a single, already-known URL. Strips HTML noise and returns clean prose, ready for the LLM to summarise or answer from.

**Key behaviours:**
- Requires a full URL as input — it cannot discover URLs from a query.
- Most often chained after WebSearch: the planner calls WebSearch first to find a URL, then WebExtract to read it.
- Can be called directly when the user supplies a URL in their prompt.
- Does *not* save content to disk; if persistence is required, use WebResearch (`mine_url`) instead.
- `max_words` (default 400) governs how much text is returned; increase it for lengthy articles.

**Trigger prompts:**
- `fetch the page at <url>`
- `read the content of <url>`
- `extract the text from <url>`
- `get the article at <url>`
- `summarise the page at <url>`
- `what does this page say: <url>`
- `read this link and tell me about it: <url>`
- (also triggered implicitly by the planner when a prior WebSearch result needs to be read)

---

### WebResearch

**Purpose:** Mine and archive web content into the structured `webresearch/` workspace for later analysis or presentation. This is the only skill that writes to disk.

**Key behaviours:**
- Two entry points:
  - `mine_url` — fetches one URL and saves it as `source.md` under the named domain.
  - `mine_search` — runs a DuckDuckGo search and saves the ranked results list as `results.md`.
- Both require a `domain` label (e.g. `"CarIndustry"`, `"AIModels"`, `"GeneralNews"`). The domain determines the directory branch and acts as a thematic filing key.
- Files are automatically placed in a dated, numbered folder: `webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/`.
- Stage 1 (`01-Mine`) is raw capture. Stages 2 and 3 (`02-Analysis`, `03-Presentation`) share the same folder structure and are intended for downstream processing skills.
- Return value is the absolute path to the saved file — this is what gets surfaced in the LLM's final answer.
- `mine_url` works best on article-level URLs. For homepages or section index pages, run PageAssess first to classify the page and discover individual article links to mine.
- `mine_search(fetch_content=True)` fetches each result URL and embeds extracted prose inline,
  making the saved `results.md` self-contained with article text rather than just snippets.
  Results with fewer than 120 extracted words are flagged as index pages. Use `content_words`
  to control how much prose to embed per result (default 200 words, max 600).

**Trigger prompts — mine a specific URL:**
- `mine this URL into the <domain> research area: <url>`
- `save <url> to the <domain> research area`
- `fetch and save <url> to <domain>`
- `archive the page at <url> in the <domain> domain`
- `store this article in <domain>: <url>`

**Trigger prompts — mine a search query:**
- `search for <topic> and save the results to the <domain> research area`
- `mine the web for <topic> and file it under <domain>`
- `research <topic> and save it to <domain>`
- `search for <query> and store the results in the <domain> research area`
- `mine the web for information about <topic> in the <domain> domain`

**Trigger prompts — mine a search with inline article content:**
- `search for <query> and save results with article content to <domain>`
- `search for <query> and save full article text to <domain>`
- `mine a search for <query> with content into <domain>`

---

### PageAssess

**Purpose:** Fetch a URL and classify it before deciding whether to mine it. Returns a structured dict with page type classification, word count, a prose preview, and a list of article-candidate links filtered by topic.

**Key behaviours:**
- Single entry point: `assess_page(url, topic="", max_links=10)`.
- Classification is deterministic (no LLM): `word_count` and link-to-text ratio determine whether the page is `"article"`, `"index"`, or `"mixed"`.
- Links are extracted from the main content area only — `<nav>`, `<header>`, `<footer>`, and heuristically identified noise containers are pruned first.
- If `topic` is provided, returned links are ranked by token overlap with the topic string.
- Does *not* write any files to disk.
- Canonical use: run before `mine_url` when you don't know what kind of page a URL leads to.

**Trigger prompts:**
- `assess the page at <url>`
- `assess <url> for topic <topic>`
- `is <url> an article or a listing page`
- `what kind of page is <url>`
- `find article links on <url> about <topic>`
- `get links from <url> related to <topic>`

**Planner decision guide:**

| `page_type` returned | Recommended next step |
|---|---|
| `"article"` | Call `mine_url` directly |
| `"index"` | Use `article_links` from the result to discover individual article URLs; call `mine_url` on those |
| `"mixed"` | Try `mine_url`; if `word_count < 200` also follow `article_links` |

---

### Planner guidance: which skill to use when

The planner should apply this decision logic:

1. **User provides a URL and wants to read it now, no saving needed → WebExtract**
2. **User wants to search and get an answer now, no saving needed → WebSearch (+ optionally WebExtract)**
3. **User wants to save / archive / mine / file content for later → WebResearch**
4. **User says "mine", "save to the X research area", "file under X domain", "store in X" → always WebResearch**, never WebSearch or WebExtract
5. **User gives a URL and explicitly wants it saved → WebResearch (`mine_url`)**
6. **User gives a query and explicitly wants results saved → WebResearch (`mine_search`)**
7. **User gives a URL that might be a homepage, section page, or landing page → PageAssess first**, then route based on `page_type`
8. **User wants saved results to include article prose, not just snippets → WebResearch `mine_search(fetch_content=True)`**

The critical distinctions:
- **WebSearch, WebExtract, and PageAssess are ephemeral** — their output exists only in the LLM's current context window.
- **WebResearch is persistent** — it always writes a file to `webresearch/01-Mine/`.
- **PageAssess is a router** — it never mines content itself but tells the planner what kind of page a URL is so the right skill can be called next.
