# Skills Summary

Single JSON payload for orchestration planning.

{
  "schema_version": "1.0",
  "skills_root": "code/skills",
  "skills": [
    {
      "skill_name": "DateTime Skill",
      "relative_path": "code/skills/DateTime/skill.md",
      "purpose": "Provide a current date-time string that can be prepended to a later LLM prompt.",
      "module": "code/skills/DateTime/datetime_skill.py",
      "functions": [
        "build_prompt_with_datetime(\"Summarize these notes\")",
        "build_prompt_with_datetime(prompt: str)",
        "get_datetime_string()"
      ],
      "inputs": [
        "`get_datetime_string()`",
        "No arguments.",
        "`build_prompt_with_datetime(prompt: str)`",
        "`prompt`: the downstream LLM prompt text."
      ],
      "outputs": [
        "`get_datetime_string()` returns a string in local time:",
        "Format: `Current date/time: YYYY-MM-DD HH:MM:SS`",
        "`build_prompt_with_datetime(prompt: str)` returns:",
        "`Current date/time: YYYY-MM-DD HH:MM:SS\\n<prompt>`"
      ]
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information for prompt-context enrichment, including OS name, Python/Ollama versions, RAM usage, and disk usage.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "functions": [
        "build_prompt_with_system_info(\"what version of python are we running\")",
        "build_prompt_with_system_info(prompt: str)",
        "get_system_info_string()"
      ],
      "inputs": [
        "`get_system_info_string()`",
        "No arguments.",
        "`build_prompt_with_system_info(prompt: str)`",
        "`prompt`: downstream LLM prompt text."
      ],
      "outputs": [
        "`get_system_info_string()` returns a string similar to:",
        "`System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`",
        "`build_prompt_with_system_info(prompt: str)` returns:",
        "`System info: os=Windows; python=3.14.2; ollama=0.17.5; ram_used=12.34 GiB; ram_available=19.66 GiB; disk_used=110.25 GiB; disk_available=401.75 GiB`"
      ]
    }
  ]
}
