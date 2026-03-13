# Memory Skill

## Purpose
Persist user-stated facts, preferences, and project context across sessions so the agent can recall relevant background in future conversations.

Facts are stored in `memory_store.json` as structured entries with a category, timestamps, and access tracking. A newer fact on the same subject supersedes the older one rather than adding a duplicate.

### What gets stored
The memory skill stores **durable, user-stated facts** - things the user says are true about themselves, their preferences, or the problem domain:
- **Identity**: "my name is Dave"
- **Preference**: "I prefer concise answers", "the default model is gpt-oss:20b"
- **Project**: "this project is called MiniAgentFramework", "we are building an LLM orchestration framework"
- **Environment**: "our repository root path is c:/Util/...", "we are running Python 3.14.2"

### What does NOT get stored
- Questions ("what version is running?", "how much RAM is available") - even without a `?`
- Imperative commands ("show me...", "list files", "output the time")
- Ephemeral data requests (current time, current stats)
- General knowledge (capitals, scientific definitions)

### Storage format
`memory_store.json` - JSON object with schema_version and an entries array. Each entry:
```json
{
  "id":            "a1b2c3d4",
  "stored":        "2026-03-13 10:00:00",
  "updated":       null,
  "category":      "project",
  "fact":          "this project is called MiniAgentFramework",
  "access_count":  3,
  "last_accessed": "2026-03-13 11:00:00"
}
```
Categories: `identity`, `preference`, `project`, `environment`, `general`.

On first run the legacy `memory_store.txt` is automatically migrated to JSON.

## Interface
- Module: `code/skills/Memory/memory_skill.py`
- Primary functions:
  - `extract_environment_facts(user_prompt: str)`
  - `store_prompt_memories(user_prompt: str)`
  - `recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)`
  - `get_memory_store_text()`

## Input
- `extract_environment_facts(user_prompt: str)`
  - `user_prompt`: raw user text to inspect for durable environment facts.
- `store_prompt_memories(user_prompt: str)`
  - `user_prompt`: prompt used for extraction and deduplicated storage.
- `recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25)`
  - `user_prompt`: current prompt to use as relevance query.
  - `limit`: max number of returned memories.
  - `min_score`: minimum token-overlap relevance threshold.
- `get_memory_store_text()`
  - No arguments.

## Output
- `extract_environment_facts(...)` returns a list of candidate environment-specific facts.
- `store_prompt_memories(...)` returns a status string - e.g. "Stored 1 new memory fact(s)." or "Updated 1 existing memory fact(s)."
- `recall_relevant_memories(...)` returns a formatted, ranked memory recall string with categories.
- `get_memory_store_text()` returns the full pretty-printed JSON of the memory store.

## Example
- `store_prompt_memories("Our workspace path is c:/Util/GithubRepos/MiniAgentFramework")`
  - `Stored 1 new memory fact(s).`
- `store_prompt_memories("Our workspace path is c:/Util/NewLocation")`
  - `Updated 1 existing memory fact(s).`  (supersedes the previous entry)
- `recall_relevant_memories("what is our workspace path")`
  - `Relevant memories:`
  - `- [environment] (0.60) Our workspace path is c:/Util/NewLocation [updated: 2026-03-13 10:00:00]`
