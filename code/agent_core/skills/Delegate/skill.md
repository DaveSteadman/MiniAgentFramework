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
  - `delegate(prompt: str, instructions: str = "", max_iterations: int = 3)`

## Parameters

### `delegate(prompt, instructions = "", max_iterations = 3)`
- `prompt` *(required)* - the child task to execute. Must be a complete, self-contained question or instruction.
- `instructions` *(optional)* - extra steering prepended to the child prompt, e.g. "research thoroughly and return a concise answer with evidence".
- `max_iterations` *(optional, default 3)* - maximum tool-calling rounds for the child run, 1-8 recommended.

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
