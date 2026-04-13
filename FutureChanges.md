# Future Changes

Ideas requiring design thought before implementation. Not committed to, not prioritised.

Done items are removed; see ChangeLog.md for what shipped. Last reviewed: 2026-04-13.

---

## Improvements

### 1. System maturity

Continue to review and polish the code, running the test prompts and controllably measure and
improve capability and performance.
Develop three READ_USECASE_XXXX files to discuss real world usage.


### 2. Test assert auto-detection of no-results responses

`test_web_prompts.json` already annotates research prompts with `not_contains|no results`,
which catches the silent-block pattern for web tests. The gap is everywhere else: prompts in
`default_prompts.json` and any future test file can silently pass with a "No results were
found" response if no assert is supplied.

Option A (done for web prompts, extend to others): audit remaining prompt files and add
`not_contains|No results were found` to all research and Wikipedia prompts that lack
an assert.

Option B (systemic): teach `test_wrapper.py` to treat any response starting with
"No results were found" or "Search failed" as a FAIL unless the prompt carries an explicit
`allow_no_results` flag. Catches future regressions without per-prompt annotation.

Option B is the more robust fix but needs the escape hatch to avoid false failures on prompts
that legitimately test the no-results path.

---

### 3. Scratchpad eviction / size limit

The in-process scratchpad (`scratchpad.py`) grows without bound. A WebResearch run saves
multiple `research_page_*` entries that are never cleaned unless the session is reset.
Long scheduled runs or multi-research sessions accumulate stale data that inflates the
key-name list injected into every system prompt.

Option: simple LRU cap - reject `scratch_save` (or evict the oldest key) when the store
exceeds, say, 30 entries. Alternatively, tag entries with a TTL at save time and lazily
evict expired entries on `scratch_list`.

Question to resolve: should the cap apply to all keys or only `research_page_*` style
auto-generated ones?

---

### 4. Delegate transparency - sub-task timing

Delegate tasks are the slowest category (19-64s in practice) with no visibility into which
sub-prompts ran or how long each took. The only way to diagnose a slow delegate run is to
read the raw log file.

Option: have `delegate_skill.py` write a structured timing entry into the scratchpad
(e.g. `delegate_timing_<n>`) after each sub-run, containing sub-prompt text and wall-clock
duration. The orchestrator could then surface this on request.

Minimal version: log sub-prompt durations to the session log at INFO level so they appear
under `/logs` without any scratchpad overhead.

---

## New Capabilities

### 5. Self-performance skill (PerfInsight)

The agent cannot reason about its own effectiveness. It has all the data - structured CSV test
results under `controldata/test_results/` - but no skill to read them.

A `PerfInsight` skill (or extension to `FileAccess`) that can:
- load and parse test_results CSVs
- compute per-suite PASS rates and median/p95 durations
- surface the five slowest prompts and any failure clusters
- answer prompts like "how did the last test run go?" or "which skill is the slowest?"

The CSV schema is already stable. A lightweight `GET /test-summary` API route for the web UI
would complement this - surfacing recent run stats without starting a chat session.

---

### 6. Search result disk cache

DuckDuckGo results fetched during one test run are thrown away and re-fetched in the next.
Repeated test runs on identical prompts hammer the same queries and contribute to rate-limiting.
Note: `webpage_utils.py` has an in-process URL LRU cache, but that does not survive across
runs and does not cover search query results.

Step 1 - measure waste before caching: instrument `web_search_skill.py` and `webpage_utils.py`
to log how many URLs are returned per query versus how many are actually fetched by a subsequent
WebFetch or WebResearch call in the same session. The ratio of fetched-to-returned is a concrete
"unused result" metric - a complement to pass/fail that shows how much network work was
discarded. Aggregate this across a standard test run to establish a baseline waste figure before
any cache is built.

Step 2 - cache: a file-based cache in `controldata/search_cache/` keyed by
`sha256(query_normalised + date)`, stored as JSON, with a configurable TTL (default 24h).
Cache hits skip the network entirely - preventing rate-limit accumulation and making research
reproducible across runs on the same day. The waste metric from Step 1 becomes the before/after
measure of cache effectiveness.

Questions: share cache across scheduler and interactive sessions? Invalidate earlier for
time-sensitive queries (prompts containing "today", "latest", "current")?

---

### 7. Per-skill retry configuration in skill.md

Network-bound skills (WebSearch, WebFetch, WebResearch, Wikipedia) fail transiently but the
framework never retries them automatically - the LLM has to re-invoke the tool. The
DuckDuckGo empty-result retry was added directly to `web_search_skill.py` with no general
mechanism behind it.

Option: add `retries` and `retry_delay_seconds` fields to the `skill.md` spec, read by
`execute_tool_call` in `skill_executor.py`. When a skill returns a recognised error sentinel
and declares retries, `execute_tool_call` re-calls the function after the delay before
surfacing the failure to the LLM.

This makes retry policy per-skill rather than baked into individual skill files, and combines
naturally with item 2 (consistent error sentinel detection).

---

### 8. MCP server integration

The agent has no way to consume tools exposed by an external MCP (Model Context Protocol)
server. All tools must currently be written as local Python skill modules with a `skill.md`
descriptor.

Design: additive, not a replacement for the existing skill system. MCP tools would be a
second source alongside local skills, with the same tool definitions merged before being sent
to the LLM.

Changes required:
- New `mcp_client.py` module - connects to a configured MCP server and queries its tool list
  at startup; dispatches tool calls and returns results as `ToolCallResult` objects.
- `skills_catalog_builder.py` - add a step that fetches MCP tool definitions and merges them
  into the catalog sent to the LLM.
- `skill_executor.py` / `tool_loop.py` - when a tool call is returned by the LLM, check
  whether the tool name belongs to an MCP server; if yes, dispatch via `mcp_client.py`;
  if no, continue with the existing `importlib` Python dispatch path.

MCP servers are configured in `default.json`. Local Python skills are completely unchanged.
The existing allow-list security model is extended to cover MCP tool names.
