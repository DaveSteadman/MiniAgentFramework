# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
import subprocess
import sys


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _get_python_version() -> str:
    return sys.version.split()[0]


# ----------------------------------------------------------------------------------------------------
def _get_ollama_version() -> str:
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
        raw_output = f"{result.stdout} {result.stderr}".strip()
        if result.returncode != 0:
            return "unknown"

        match = re.search(r"(\d+\.\d+\.\d+)", raw_output)
        if match:
            return match.group(1)

        return raw_output or "unknown"
    except Exception:
        return "unknown"


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def get_system_info_string() -> str:
    python_version = _get_python_version()
    ollama_version = _get_ollama_version()
    return f"System info: python={python_version}; ollama={ollama_version}"


# ----------------------------------------------------------------------------------------------------
def build_prompt_with_system_info(prompt: str) -> str:
    return get_system_info_string()
