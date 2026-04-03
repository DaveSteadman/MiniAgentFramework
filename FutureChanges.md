# Future Changes

Ideas requiring design thought before implementation. Not committed to, not prioritised.

---

## Improvements

### 2. Test assert coverage

Many research and Wikipedia test prompts have no assert at all, so "No results were found for..."
passes silently. The 6 DuckDuckGo failures in the April 2026 test run would have been flagged
much earlier with a simple default-deny assert.

Option A: add `not_contains|No results were found` to all research-class prompts in the prompt
JSON files. Low-cost, catches the silent-block pattern directly.

Option B: teach `test_wrapper.py` to treat any response that starts with "No results were found"
as a FAIL unless the prompt is explicitly testing the no-results path. Avoids per-prompt
annotation but is more fragile.

---

### 3. Scratchpad eviction / size limit

The in-process scratchpad (`scratchpad.py`) grows without bound. A WebResearch run saves
multiple `research_page_*` entries that are never cleaned unless the session is reset.
Long scheduled runs or multi-research sessions will accumulate stale data that inflates
the key-name list injected into every system prompt.

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

Option: have `Delegate/delegate_skill.py` write a structured timing entry into the scratchpad
(e.g. `delegate_timing_<n>`) after each sub-run, containing sub-prompt text and wall-clock
duration. The orchestrator could then include this in the final response footnote on request.

Minimal version: just log sub-prompt durations to the session log at INFO level so they
surface in `/logs`.

---

## New Capabilities

### 5. Self-performance skill (PerfInsight)

The agent cannot currently reason about its own effectiveness. It has all the data it needs -
structured CSV test results under `controldata/test_results/` - but no skill to read them.

A `PerfInsight` skill (or extend `FileAccess`) that can:
- load and parse test_results CSVs
- compute per-suite PASS rates and median/p95 durations
- surface the five slowest prompts and any failure clusters
- answer prompts like "how did the last test run go?" or "which skill is the slowest?"

This directly supports the goal of the agent being able to consider its own performance. The
CSV schema is already well-defined and stable.

Related: a lightweight `GET /test-summary` API endpoint for the web UI to surface recent run
stats without starting a full chat session.

---

### 6. Search result disk cache

DuckDuckGo results fetched during one test run are thrown away and re-fetched in the next.
Repeated test runs on the same prompts hammer the same queries, which contributes to rate-limiting.

Option: a file-based result cache in `controldata/search_cache/` keyed by
`sha256(query_normalised + date)`, stored as JSON, with a configurable TTL (default 24h).
Cache hits skip the network entirely - both preventing rate-limit accumulation and making
research reproducible across runs on the same day.

Questions: should the cache be shared across scheduler and interactive sessions? Should cache
entries be invalidated earlier for time-sensitive queries (e.g. "latest news")?

---

### 7. Adaptive context compression

The orchestrator has a fixed `num_ctx` window and a `COMPACT_THRESHOLD` constant but there is
no active compression pass when the context approaches the limit. Long multi-hop research tasks
can silently overflow, causing the model to lose early tool results mid-run.

Option: before the final synthesis call, count estimated tokens in `_last_messages`. If over
`COMPACT_THRESHOLD * num_ctx`, inject a summarisation sub-call that condenses prior tool
results into a compact evidence block, then replace the bulky messages with the summary.

This already has partial scaffolding (`COMPACT_THRESHOLD` constant exists). The main work is
triggering it reliably and ensuring the summary does not lose key facts.

---

### 8. Post-run test summary report

After each `/test` run the framework produces a CSV. Reading and interpreting it requires
opening a spreadsheet or running analysis manually. The April 2026 run produced 8 failures
that were only discovered by reading 900 CSV rows.

Option: generate a Markdown summary alongside the CSV at
`controldata/test_results/<date>/summary_<runid>.md`:
- suite-by-suite PASS/FAIL table with counts
- five slowest prompts
- failure reasons categorised (network block, assert mismatch, model error)
- total wall-clock time

Low implementation cost: `test_wrapper.py` already has all the data in memory at run end.

---

### 9. Per-skill retry configuration in skill.md

Network-bound skills (WebSearch, WebFetch, WebResearch, Wikipedia) fail transiently but the
framework never retries them - the LLM has to re-invoke the tool. The DuckDuckGo fix (empty-
result retry) was added directly to `web_search_skill.py` but there is no general mechanism.

Option: add a `retries` and `retry_delay_seconds` field to the `skill.md` spec, read by
`execute_tool_call` in `skill_executor.py`. When a skill returns a known error sentinel (see
item 1 above) and the skill declares retries, `execute_tool_call` re-calls the function after
the delay before surfacing the error to the LLM.

This combines naturally with item 1 (error sentinel detection) and makes retry policy
per-skill rather than baked into individual skill files.
