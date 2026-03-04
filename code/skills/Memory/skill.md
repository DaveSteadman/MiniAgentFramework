# Memory Skill

## Purpose
Extract environment-specific facts from user prompts, store unique facts in a local text memory file, and recall relevant memories for future prompts.

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
