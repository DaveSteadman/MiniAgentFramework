# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# SystemInfo skill module for the MiniAgentFramework.
#
# Provides a callable function that the orchestration planner can select when a user prompt
# requires information about the runtime environment:
#   - get_system_info_string()  -- returns OS, Python version, Ollama version, RAM usage, and disk usage.
#
# This module is also imported directly by main.py to inject system info as ambient prompt context
# on every orchestration turn, guaranteeing that any prompt touching hardware or runtime state
# receives accurate data even when the planner does not explicitly select this skill.
#
# This module is discovered automatically by skills_catalog_builder.py via the accompanying
# skill.md definition file and added to the skills_summary.md catalog.
#
# Related modules:
#   - skill_executor.py         -- dynamically imports and calls functions from this module
#   - skills_catalog_builder.py -- reads skill.md to build the catalog entry for this skill
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import os
import re
import shutil
import subprocess
import sys
import platform
from pathlib import Path

if sys.platform.startswith("win"):
    import ctypes


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _get_python_version() -> str:
    return sys.version.split()[0]


# ----------------------------------------------------------------------------------------------------
def _get_os_name() -> str:
    platform_name = platform.system().strip().lower()
    os_name_map = {
        "windows": "Windows",
        "linux": "Linux",
        "darwin": "macOS",
    }
    if platform_name in os_name_map:
        return os_name_map[platform_name]

    low_level_name = os.name.strip().lower()
    os_name_fallback_map = {
        "nt": "Windows",
        "posix": "Linux",
        "java": "Java",
    }
    if low_level_name in os_name_fallback_map:
        return os_name_fallback_map[low_level_name]

    return "unknown"


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


# ----------------------------------------------------------------------------------------------------
def _format_bytes(num_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size  = float(max(num_bytes, 0))

    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0

    return "0 B"


# ----------------------------------------------------------------------------------------------------
def _get_memory_usage_bytes() -> tuple[int, int] | tuple[None, None]:
    if sys.platform.startswith("win"):
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memory_status           = MEMORYSTATUSEX()
        memory_status.dwLength  = ctypes.sizeof(MEMORYSTATUSEX)
        call_success            = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status))
        if call_success:
            total_bytes     = int(memory_status.ullTotalPhys)
            available_bytes = int(memory_status.ullAvailPhys)
            used_bytes      = max(total_bytes - available_bytes, 0)
            return used_bytes, available_bytes

    return None, None


# ----------------------------------------------------------------------------------------------------
def _get_disk_usage_bytes() -> tuple[int, int] | tuple[None, None]:
    try:
        current_path    = Path.cwd()
        disk_usage      = shutil.disk_usage(current_path)
        used_bytes      = int(disk_usage.used)
        available_bytes = int(disk_usage.free)
        return used_bytes, available_bytes
    except Exception:
        return None, None


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def get_system_info_string() -> str:
    os_name        = _get_os_name()
    python_version = _get_python_version()
    ollama_version = _get_ollama_version()

    ram_used_bytes, ram_available_bytes   = _get_memory_usage_bytes()
    disk_used_bytes, disk_available_bytes = _get_disk_usage_bytes()

    ram_used_text       = _format_bytes(ram_used_bytes) if ram_used_bytes is not None else "unknown"
    ram_available_text  = _format_bytes(ram_available_bytes) if ram_available_bytes is not None else "unknown"
    disk_used_text      = _format_bytes(disk_used_bytes) if disk_used_bytes is not None else "unknown"
    disk_available_text = _format_bytes(disk_available_bytes) if disk_available_bytes is not None else "unknown"

    return (
        f"System info: os={os_name}; python={python_version}; ollama={ollama_version}; "
        f"ram_used={ram_used_text}; ram_available={ram_available_text}; "
        f"disk_used={disk_used_text}; disk_available={disk_available_text}"
    )
