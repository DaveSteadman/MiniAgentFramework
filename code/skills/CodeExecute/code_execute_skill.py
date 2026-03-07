# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# CodeExecute skill module for the MiniAgentFramework.
#
# Runs a Python code snippet supplied by the planner inside a sandboxed environment with a
# restricted import whitelist, stripped dangerous builtins, and a wall-clock timeout.  Captured
# stdout is returned as a plain string so the result can be chained into FileAccess or returned
# directly to the final LLM prompt.
#
# Intended use-case: generating computed data (sequences, tables, calculations) that no other
# skill can produce.  The planner provides the code; this skill executes it safely.
#
# Related modules:
#   - skill_executor.py         -- dynamically imports and calls functions from this module
#   - skills_catalog_builder.py -- reads skill.md to build the catalog entry for this skill
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import builtins
import io
import sys
import threading


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_EXECUTION_TIMEOUT_S = 15

# Modules the sandboxed code is permitted to import.
_ALLOWED_MODULES = frozenset({
    "math", "cmath", "decimal", "fractions", "statistics",
    "itertools", "functools", "operator",
    "string", "re", "textwrap",
    "json", "csv", "io",
    "datetime", "time", "calendar",
    "collections", "heapq", "bisect", "array",
    "random",
})

# Builtins that are removed from the sandboxed namespace.
_BLOCKED_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "breakpoint", "input", "memoryview",
})


# ====================================================================================================
# MARK: SANDBOX HELPERS
# ====================================================================================================
def _make_safe_import(allowed: frozenset):
    """Return a __import__ replacement that only allows whitelisted top-level modules."""
    real_import = builtins.__import__

    def _safe_import(name: str, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level not in allowed:
            raise ImportError(
                f"Import '{name}' is not permitted in sandboxed execution. "
                f"Allowed modules: {sorted(allowed)}"
            )
        return real_import(name, *args, **kwargs)

    return _safe_import


def _make_restricted_globals() -> dict:
    safe_builtins = {
        k: getattr(builtins, k)
        for k in dir(builtins)
        if k not in _BLOCKED_BUILTINS and not k.startswith("__")
    }
    safe_builtins["__import__"] = _make_safe_import(_ALLOWED_MODULES)
    return {"__builtins__": safe_builtins}


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def run_python_snippet(code: str) -> str:
    """Execute a Python snippet in a sandboxed environment and return captured stdout.

    The snippet must write its final output via print() calls.
    Imports are restricted to a safe whitelist; os, sys, subprocess, and file I/O are blocked.
    Execution is limited to _EXECUTION_TIMEOUT_S seconds.

    Args:
        code: Python source code to execute.

    Returns:
        Captured stdout as a string, or an error string beginning with "Error:".
    """
    code = str(code or "").strip()
    if not code:
        return "Error: No code provided to run_python_snippet."

    stdout_buf   = io.StringIO()
    result_slot: list[str] = []
    error_slot:  list[str] = []

    def _run() -> None:
        old_stdout = sys.stdout
        sys.stdout = stdout_buf
        try:
            exec(code, _make_restricted_globals())  # noqa: S102
            result_slot.append(stdout_buf.getvalue())
        except Exception as exc:  # noqa: BLE001
            error_slot.append(f"Error: {exc}")
        finally:
            sys.stdout = old_stdout

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_EXECUTION_TIMEOUT_S)

    if thread.is_alive():
        return f"Error: Code execution timed out after {_EXECUTION_TIMEOUT_S}s."
    if error_slot:
        return error_slot[0]
    output = result_slot[0] if result_slot else ""
    if not output.strip():
        return "Error: Code produced no output. Make sure the snippet uses print() to emit results."
    return output
