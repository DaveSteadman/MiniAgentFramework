# Wikipedia Skill

## Purpose
Look up a topic on Wikipedia and return a plain-text article summary. Use this when the LLM needs factual reference data about a person, place, concept, event, or technology - any time it would benefit from an authoritative definition or background.

## Interface
- Module: `code/skills/Wikipedia/wikipedia_skill.py`
- Primary functions:
  - `lookup_wikipedia(topic: str, timeout: int = 15)`

## Input
- `topic`: the subject to look up (required). Can be a name, term, acronym, or short phrase.
- `timeout`: network timeout in seconds (optional, default 15).

## Output
- Returns a plain-text block starting with `Wikipedia - <article title>` followed by the article extract (up to 400 words).
- Returns `No Wikipedia data found for '<topic>'` when no matching article exists or no useful extract is available.

## How it works
1. Sends the topic to the Wikipedia OpenSearch API to find the best-matching article title.
2. Fetches the article summary via the Wikipedia REST Summary API (`/api/rest_v1/page/summary/`).
3. Returns the `extract` field - pre-cleaned plain text - truncated to 400 words.
4. Skips disambiguation pages and tries the next candidate automatically.

## Typical trigger phrases
- `what is <topic>`
- `tell me about <topic>`
- `look up <topic> on Wikipedia`
- `get background on <topic>`
- `who is <person>`
- `what is the history of <topic>`

## Examples
- `lookup_wikipedia("Python programming language")`
- `lookup_wikipedia("Eiffel Tower")`
- `lookup_wikipedia("quantum entanglement")`
- `lookup_wikipedia("Marie Curie")`

## Notes
- Uses only Python stdlib (urllib, json) - no third-party dependencies.
- No API key required.
- English Wikipedia only.
