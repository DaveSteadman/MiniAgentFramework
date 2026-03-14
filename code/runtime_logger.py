# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Session logger that writes timestamped run output to both stdout and a persistent log file.
#
# SessionLogger is used by main.py to record every stage of an orchestration run - tool call rounds,
# tool execution outputs, the final LLM response, and token metrics - so that runs can be reviewed
# after the fact without re-executing. Each session writes to a unique file named with the run timestamp.
#
# Related modules:
#   - main.py  -- creates a SessionLogger instance and logs all orchestration stages through it
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
SECTION_SEPARATOR = "=" * 100
HORIZONTAL_SEPARATOR = "-" * 100


# ====================================================================================================
# MARK: TEE WRITER
# ====================================================================================================
class _TeeWriter:
    """Wraps sys.stdout so that print() calls go to both the console and the log file."""

    def __init__(self, original, file_path: Path):
        self._original  = original
        self._file_path = file_path

    def write(self, text: str) -> None:
        self._original.write(text)
        with self._file_path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def flush(self) -> None:
        self._original.flush()

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", None) or "utf-8"

    @property
    def errors(self) -> str:
        return getattr(self._original, "errors", None) or "replace"


# ====================================================================================================
# MARK: LOGGER
# ====================================================================================================
class SessionLogger:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------------------------------------------
    def log(self, message: str = "") -> None:
        text = str(message)

        try:
            print(text)
        except UnicodeEncodeError:
            output_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            safe_text = text.encode(output_encoding, errors="replace").decode(output_encoding, errors="replace")
            print(safe_text)

        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    # ----------------------------------------------------------------------------------------------------
    def log_section(self, title: str) -> None:
        stamped = f"{title}  [{datetime.now().strftime('%H:%M:%S')}]"
        self.log("")
        self.log(SECTION_SEPARATOR)
        self.log(stamped)
        self.log(SECTION_SEPARATOR)
        self.log("")

    # ----------------------------------------------------------------------------------------------------
    def log_separator(self) -> None:
        self.log("")
        self.log(HORIZONTAL_SEPARATOR)
        self.log("")

    # ----------------------------------------------------------------------------------------------------
    def log_file_only(self, message: str = "") -> None:
        """Write to the log file only - no stdout. Used for verbose orchestration detail in chat mode."""
        text = str(message)
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    # ----------------------------------------------------------------------------------------------------
    def log_section_file_only(self, title: str) -> None:
        """Write a section header to the log file only - no stdout."""
        stamped = f"{title}  [{datetime.now().strftime('%H:%M:%S')}]"
        self.log_file_only("")
        self.log_file_only(SECTION_SEPARATOR)
        self.log_file_only(stamped)
        self.log_file_only(SECTION_SEPARATOR)

    # ----------------------------------------------------------------------------------------------------
    @contextmanager
    def tee_stdout(self):
        """Context manager: redirect sys.stdout so print() calls inside skill code go to both
        the console and the log file for the duration of the block."""
        original    = sys.stdout
        sys.stdout  = _TeeWriter(original, self.file_path)
        try:
            yield
        finally:
            sys.stdout = original


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def create_log_file_path(log_dir: Path) -> Path:
    # Organise logs into YYYY-MM-DD dated subfolders to keep the logs root manageable.
    now      = datetime.now()
    date_dir = log_dir / now.strftime("%Y-%m-%d")
    return date_dir / f"run_{now.strftime('%Y%m%d_%H%M%S')}.txt"
