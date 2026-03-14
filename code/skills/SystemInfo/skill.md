# SystemInfo Skill

## Purpose
Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.
This skill should be selected for any request that asks about the system, machine, hardware, runtime, environment, OS, Python or Ollama version,
RAM, memory, disk space, storage, available space, or free space - including indirect phrasing such as "can we fit", "do we have enough",
"how much is available", "how much is free", "what OS", "what version", "is there enough", "show me specs", or "health".

## Interface
- Module: `code/skills/SystemInfo/system_info_skill.py`
- Function: `get_system_info_dict()`

## Input
- `get_system_info_dict()`
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
- `get_system_info_dict()` returns a structured dict with individually addressable fields:
  - `os` (str) - OS name, e.g. `"Windows"`
  - `python_version` (str) - e.g. `"3.10.11"`
  - `ollama_version` (str) - e.g. `"0.18.0"`
  - `ram_used_gb` (float) - RAM in use in GiB, e.g. `30.80`
  - `ram_available_gb` (float) - RAM free in GiB, e.g. `96.49`
  - `disk_used_gb` (float) - disk used in GiB, e.g. `937.34`
  - `disk_available_gb` (float) - disk free in GiB, e.g. `924.72`

## Example
- `get_system_info_dict()` -> `{"os": "Windows", "python_version": "3.14.2", "ollama_version": "0.17.5", "ram_used_gb": 12.34, "ram_available_gb": 19.66, "disk_used_gb": 110.25, "disk_available_gb": 401.75}`
- Prompt intent examples:
  - "do we have enough disk space to add a 50 GB file?" -> `get_system_info_dict()`, read `disk_available_gb`
  - "how much RAM is available?" -> `get_system_info_dict()`, read `ram_available_gb`
  - "what version of python is running?" -> `get_system_info_dict()`, read `python_version`
  - "show current system info" -> `get_system_info_dict()`; LLM formats the dict for display
  - "write system info to a file" -> `get_system_info_dict()` then pass result to FileAccess skill
  - "append RAM and disk to a CSV file" -> `get_system_info_dict()`, then reference `${outputN.ram_available_gb}` and `${outputN.disk_available_gb}` in the FileAccess call
