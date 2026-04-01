# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Thin skill wrapper for the Delegate orchestration primitive.
#
# Validates arguments and forwards the call to delegate_subrun() in orchestration.py.
# All child-run logic - context isolation, depth capping, iteration budget, tool filtering -
# lives in the core function, not here.
#
# Related modules:
#   - orchestration.py  -- delegate_subrun (core implementation)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from agent_core.orchestration import delegate_subrun


# ====================================================================================================
# MARK: INTERFACE
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def delegate(
    prompt: str,
    instructions: str = "",
    max_iterations: int = 3,
) -> dict:
    """Spawn an isolated child orchestration context for a focused sub-task.

    Use this when the user explicitly says 'delegate', or when a sub-problem
    needs its own multi-step tool-calling loop without polluting the parent
    context. The child runs independently and returns a compact answer dict
    with keys: status, answer, delegate_prompt, depth, max_iterations.
    Do NOT use for trivial single-tool operations - call the tool directly instead.
    """
    return delegate_subrun(
        prompt         = str(prompt or "").strip(),
        instructions   = str(instructions or "").strip(),
        max_iterations = int(max_iterations or 3),
    )
