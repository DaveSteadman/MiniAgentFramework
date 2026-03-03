# SystemInfo Skill

## Purpose
Provide runtime system information for prompt-context enrichment, including Python and Ollama versions.

## Interface
- Module: `code/skills/SystemInfo/system_info_skill.py`
- Primary function: `get_system_info_string()`
- Optional function: `build_prompt_with_system_info(prompt: str)`

## Input
- `get_system_info_string()`
  - No arguments.
- `build_prompt_with_system_info(prompt: str)`
  - `prompt`: downstream LLM prompt text.

## Output
- `get_system_info_string()` returns a string similar to:
  - `System info: python=3.14.2; ollama=0.17.5`
- `build_prompt_with_system_info(prompt: str)` returns:
  - `System info: python=3.14.2; ollama=0.17.5`

## Example
- `get_system_info_string()` -> `System info: python=3.14.2; ollama=0.17.5`
- `build_prompt_with_system_info("what version of python are we running")` ->
  - `System info: python=3.14.2; ollama=0.17.5`
