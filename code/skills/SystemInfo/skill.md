# SystemInfo Skill

## Purpose
Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.
This skill should be selected for any request that asks about the system, machine, hardware, runtime, environment, OS, Python or Ollama version,
RAM, memory, disk space, storage, available space, or free space — including indirect phrasing such as "can we fit", "do we have enough",
"how much is available", "how much is free", "what OS", "what version", "is there enough", "show me specs", or "health".

## Interface
- Module: `code/skills/SystemInfo/system_info_skill.py`
- Function: `get_system_info_string()`

## Input
- `get_system_info_string()`
  - No arguments.
- Typical trigger phrases (select this skill for any of these concepts):
  - `system information`, `system info`, `system health`
  - `machine info`, `runtime info`, `environment information`
  - `RAM usage`, `RAM available`, `how much RAM`, `available memory`, `used memory`, `memory usage`
  - `disk usage`, `disk space`, `disk available`, `free disk`, `free space`, `available space`
  - `can we fit`, `do we have enough space`, `is there enough disk`, `enough room`, `enough storage`
  - `python version`, `what version of python`, `ollama version`, `what version of ollama`
  - `what OS`, `operating system`, `what platform`, `what machine`
  - `show specs`, `show health`, `system stats`, `resource usage`

## Output
- `get_system_info_string()` returns a single string, for example:
  - `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`

## Example
- `get_system_info_string()` -> `System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`
- Prompt intent examples:
  - "do we have enough disk space to add a 50 GB file?" -> select this skill; the LLM reads disk_available from the output
  - "how much RAM is available?" -> select this skill
  - "what version of python is running?" -> select this skill
  - "show current system info including RAM and disk usage" -> select this skill
  - "create a file with system info in it" -> select this skill first, then pass result to FileAccess skill
