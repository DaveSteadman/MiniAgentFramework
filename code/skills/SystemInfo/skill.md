# SystemInfo Skill

## Purpose
Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.
This skill should be selected for requests mentioning system information, system info, machine info, runtime info, environment info, RAM, or disk usage.

## Interface
- Module: `code/skills/SystemInfo/system_info_skill.py`
- Primary function: `get_system_info_string()`
- Optional function: `build_prompt_with_system_info(prompt: str)`

## Input
- `get_system_info_string()`
  - No arguments.
- `build_prompt_with_system_info(prompt: str)`
  - `prompt`: downstream LLM prompt text.
- Typical trigger phrases:
  - `system information`
  - `system info`
  - `machine info`
  - `runtime info`
  - `environment information`
  - `RAM usage`
  - `disk usage`

## Output
- `get_system_info_string()` returns a string similar to:
  - `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`
- `build_prompt_with_system_info(prompt: str)` returns:
  - `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`

## Example
- `get_system_info_string()` -> `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`
- `build_prompt_with_system_info("what version of python are we running")` ->
  - `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`
- Prompt intent example: `create file abc.csv and write the system information into it in CSV format`
  - Use `get_system_info_string()` first, then pass its result to a file-write skill.
