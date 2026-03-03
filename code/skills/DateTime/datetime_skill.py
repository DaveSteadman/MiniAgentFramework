# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from datetime import datetime


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def get_datetime_string() -> str:
    current_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Current date/time: {current_local}"


# ----------------------------------------------------------------------------------------------------
def build_prompt_with_datetime(prompt: str) -> str:
    datetime_prefix = get_datetime_string()
    return f"{datetime_prefix}\n{prompt}"
