# Memory Skill

## Purpose
Persist user-stated facts, preferences, and project context across sessions so the agent can recall relevant background in future conversations.

### What gets stored
The memory skill stores **durable, user-stated facts** — things the user says are true about themselves, their preferences, or the problem domain:
- **Identity and preferences**: "my name is Dave", "I prefer concise answers", "we use gpt-oss:20b"
- **Project / domain context**: "this project is called MiniAgentFramework", "we are building an LLM orchestration framework"
- **Environment assertions**: "our repository root path is c:/Util/...", "we are running Python 3.14.2"

### What does NOT get stored
- Questions ("what version is running?", "how much RAM is available") — even without a `?`
- Imperative commands ("show me...", "list files", "output the time")
- Ephemeral data requests (current time, current stats)
- General knowledge (capitals, scientific definitions)

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
- `store_prompt_memories(...)` returns a status string describing what was stored.
- `recall_relevant_memories(...)` returns a formatted, ranked memory recall string.
- `get_memory_store_text()` returns the full text content of the memory store file.

## Example
- `store_prompt_memories("Our workspace path is c:/Util/GithubRepos/MiniAgentFramework")`
  - `Stored 1 new memory fact(s).`
- `recall_relevant_memories("what is our workspace path")`
  - `Relevant memories:`
  - `- (0.60) Our workspace path is c:/Util/GithubRepos/MiniAgentFramework [stored: 2026-03-04 20:00:00]`
