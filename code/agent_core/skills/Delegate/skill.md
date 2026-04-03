# Delegate Skill

## Purpose
Create a fresh child orchestration context for a focused sub-task. The child gets its own
isolated reasoning and tool-calling loop, runs independently, and returns a compact answer
to the parent. Use this when a sub-problem would benefit from multi-step investigation
without polluting the parent context with intermediate tool chatter.

## Trigger keyword: delegate

## Interface
- Module: `code/agent_core/skills/Delegate/delegate_skill.py`
- Functions:
  - `delegate(prompt: str, instructions: str = "", max_iterations: int = 3, output_key: str = "", scratchpad_visible_keys: list[str] | None = None, tools_allowlist: list[str] | None = None)`

## Parameters

### `delegate(prompt, instructions = "", max_iterations = 3, output_key = "", scratchpad_visible_keys = None, tools_allowlist = None)`
- `prompt` *(required)* - the child task to execute. Must be a complete, self-contained question or instruction.
- `instructions` *(optional)* - extra steering prepended to the child prompt, e.g. "research thoroughly and return a concise answer with evidence".
- `max_iterations` *(optional, default 3)* - maximum tool-calling rounds for the child run, 1-8 recommended.
- `output_key` *(optional)* - scratchpad key name to save the child's final answer under automatically.
  Mirrors `scratch_query`'s `save_result_key`. The parent can then use `scratch_query(output_key, ...)` or
  `{scratch:output_key}` downstream without capturing the answer from the return dict inline.
- `scratchpad_visible_keys` *(optional)* - list of scratchpad key names the child can see in its system prompt.
  When provided, the child's key listing is limited to only those keys. When omitted, the child sees no
  parent scratchpad keys (safe default - prevents silent context leakage from auto-saved `_tc_*` keys).
  Pass explicit keys to hand the child exactly the content it needs: e.g. `["search_hits", "page_draft"]`.
- `tools_allowlist` *(optional)* - list of function names the child is permitted to call.
  When provided, the child's tool set is restricted to only skills that expose those functions. Use to create
  focused sub-loops: e.g. `["fetch_page_text", "scratch_save"]` for a child whose only job is to fetch and
  store, or `["search_web", "lookup_wikipedia", "fetch_page_text"]` for a web-research-only child.

## Output
Returns a dictionary with:
- `status` - "ok" or "error"
- `answer` - compact final answer from the child run
- `delegate_prompt` - the child prompt actually used
- `depth` - delegation depth of the child run
- `max_iterations` - child iteration budget used

## Triggers
Invoke this skill when:
- the task contains a clear sub-problem that should be solved independently
- intermediate tool chatter from the sub-problem would pollute the parent context
- you want a focused, isolated sub-investigation before final synthesis

## Tool selection guidance
Do not use this skill for trivial one-step actions - prefer direct tool calls instead.
Prefer `delegate(...)` when the subtask may require multiple tools or iterative exploration.
Avoid recursive delegation - the framework limits delegation depth automatically.

For list-processing workflows:
- Prefer one delegate over the whole batch when the child can iterate internally.
- If you truly need multiple delegates, launch sibling delegates from the parent orchestration only.
- Do not ask a child delegate to spawn more delegates for each item in its list unless recursion is essential.
- If the task is mostly `search -> navigate -> fetch -> save`, direct tool calls are usually more reliable than per-item delegation.
