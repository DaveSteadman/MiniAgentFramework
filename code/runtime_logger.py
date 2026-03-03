# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
SECTION_SEPARATOR = "=" * 100


# ====================================================================================================
# MARK: LOGGER
# ====================================================================================================
class SessionLogger:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------------------------------------------
    def log(self, message: str = "") -> None:
        print(message)
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    # ----------------------------------------------------------------------------------------------------
    def log_section(self, title: str) -> None:
        self.log("")
        self.log(SECTION_SEPARATOR)
        self.log(title)
        self.log(SECTION_SEPARATOR)


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def create_log_file_path(log_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"run_{timestamp}.txt"
