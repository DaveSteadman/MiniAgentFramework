# Wikipedia Skill

## Purpose
Look up a topic on Wikipedia and return a plain-text article summary. Use this for authoritative factual reference data about a person, place, concept, event, or technology. For current news or live data, use WebSearch instead.

## Trigger keyword: wikipedia

## Interface
- Module: `code/skills/Wikipedia/wikipedia_skill.py`
- Functions:
  - `lookup_wikipedia(topic: str, timeout: int = 15)`

## Parameters

### `lookup_wikipedia(topic, timeout = 15)`
- `topic` *(required)* - subject to look up: a name, term, acronym, or short phrase.
- `timeout` *(optional, default 15)* - network timeout in seconds.

## Output
- `lookup_wikipedia(...)` - returns a plain-text block starting with `"Wikipedia - <article title>"` followed by the article extract (up to 400 words). Returns `"No Wikipedia data found for '<topic>'"` when no matching article is found. Skips disambiguation pages automatically and tries the next candidate.

## Triggers
Invoke this skill when the prompt contains any of these concepts or phrases:
- `what is`, `tell me about`, `who is`
- `look up on Wikipedia`, `Wikipedia article`
- `background on`, `history of`, `definition of`

## Examples
- `lookup_wikipedia("Python programming language")` - returns the Wikipedia summary
  - Returns: `"Wikipedia - Python (programming language)\nPython is a high-level..."`
- `lookup_wikipedia("Eiffel Tower")` - returns the Eiffel Tower article summary
- `lookup_wikipedia("quantum entanglement")` - returns background on the physics concept
