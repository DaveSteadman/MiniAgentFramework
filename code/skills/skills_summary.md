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
        "get_datetime_string()",
        "build_prompt_with_datetime(prompt: str)"
      ],
      "inputs": [
        "get_datetime_string() - No arguments",
        "build_prompt_with_datetime(prompt: str)"
      ],
      "outputs": [
        "get_datetime_string() returns a string: Current date/time: YYYY-MM-DD HH:MM:SS",
        "build_prompt_with_datetime(prompt: str) returns: Current date/time: YYYY-MM-DD HH:MM:SS\\n<prompt>"
      ]
    },
    {
      "skill_name": "SystemInfo Skill",
      "relative_path": "code/skills/SystemInfo/skill.md",
      "purpose": "Provide runtime system information for prompt-context enrichment, including Python and Ollama versions.",
      "module": "code/skills/SystemInfo/system_info_skill.py",
      "functions": [
        "get_system_info_string",
        "build_prompt_with_system_info"
      ],
      "inputs": [
        "get_system_info_string: no arguments",
        "build_prompt_with_system_info: prompt (str)"
      ],
      "outputs": [
        "get_system_info_string: string like 'System info: python=3.14.2; ollama=0.17.5'",
        "build_prompt_with_system_info: string like 'System info: python=3.14.2; ollama=0.17.5'"
      ]
    }
  ]
}
