# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Core orchestration layer shared by all execution modes.
#
# Provides:
#   OrchestratorConfig      -- immutable session-level settings bundle
#   ConversationHistory     -- rolling window of user/assistant turn pairs
#   resolve_execution_model -- model alias → installed Ollama model name
#   orchestrate_prompt      -- full planner → skill → LLM → validate pipeline
#
# The build_* helpers are internal to orchestrate_prompt but kept module-level so
# preprocess_prompt.py and tests can reach them if needed.
#
# Related modules:
#   - main.py                    -- creates config, dispatches modes
#   - modes/dashboard.py         -- run_dashboard_mode
#   - modes/chat.py (future)     -- run_chat_mode
#   - modes/scheduler.py (future)-- run_scheduler_mode
#   - planner_engine.py          -- create_skill_execution_plan
#   - skill_executor.py          -- execute_skill_plan_calls
#   - orchestration_validation.py-- validate_orchestration_iteration
#   - ollama_client.py           -- call_ollama_extended, list_ollama_models
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
from dataclasses import dataclass
from pathlib import Path

from ollama_client import call_ollama_extended
from ollama_client import list_ollama_models
from ollama_client import resolve_model_name
from orchestration_validation import validate_orchestration_iteration
from planner_engine import create_skill_execution_plan
from prompt_tokens import resolve_tokens
from runtime_logger import SessionLogger
from skill_executor import execute_skill_plan_calls
from skills.Memory.memory_skill import recall_relevant_memories
from skills.Memory.memory_skill import store_prompt_memories
from skills.SystemInfo.system_info_skill import get_system_info_string


# ====================================================================================================
# MARK: PATHS
# ====================================================================================================
_SKILLS_SUMMARY_PATH = Path(__file__).resolve().parent / "skills" / "skills_summary.md"


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================
@dataclass
class OrchestratorConfig:
    """Session-level configuration bundle shared by all orchestration calls.

    Passed through the orchestration layer so that adding new session-level settings
    requires only a change to this dataclass and the one construction site in main().
    Fields are intentionally mutable so slash commands (/model, /ctx) can update them
    at runtime without rebuilding the object.
    """
    resolved_model:  str
    num_ctx:         int
    max_iterations:  int
    skills_payload:  dict
    skip_final_llm:  bool = False   # /skip-final sets True; /run-final resets to False


# ====================================================================================================
# MARK: CONVERSATION HISTORY
# ====================================================================================================
class ConversationHistory:
    """Rolling window of user / assistant turn pairs.

    Keeps at most *max_turns* complete rounds (one user + one assistant message per round).
    Older turns are dropped automatically when the cap is exceeded.
    """

    def __init__(self, max_turns: int = 10):
        self._max_turns = max_turns
        self._turns: list[dict] = []

    # ----------------------------------------------------------------------------------------------------

    def add(self, user: str, assistant: str) -> None:
        self._turns.append({"role": "user",      "content": user})
        self._turns.append({"role": "assistant", "content": assistant})
        cap = self._max_turns * 2
        if len(self._turns) > cap:
            self._turns = self._turns[-cap:]

    def clear(self) -> None:
        self._turns = []

    def as_list(self) -> list[dict]:
        """Return the history as a list suitable for passing to orchestrate_prompt."""
        return list(self._turns)

    def __len__(self) -> int:
        return len(self._turns) // 2   # number of complete turns

    def __bool__(self) -> bool:
        return bool(self._turns)


# ====================================================================================================
# MARK: MODEL RESOLUTION
# ====================================================================================================
def resolve_execution_model(requested_model: str) -> str:
    """Resolve a short alias or tag to a fully-qualified installed Ollama model name.

    Falls back to the first available model (with a printed warning) rather than
    crashing, so a machine with no "20b" model still starts cleanly.
    """
    available_models = list_ollama_models()
    if not available_models:
        raise RuntimeError("No models are installed in Ollama. Pull models first, then rerun.")

    resolved = resolve_model_name(requested_model, available_models)
    if resolved is None:
        fallback = available_models[0]
        print(
            f"[model] '{requested_model}' not found \u2014 falling back to '{fallback}'.\n"
            f"        Available: {', '.join(available_models)}"
        )
        return fallback

    return resolved


# ====================================================================================================
# MARK: PROMPT BUILDING HELPERS
# ====================================================================================================
_PLANNER_ASK = (
    "Given the user prompt, select needed skills and return python_calls JSON. "
    "Choose the minimum required skills and provide explicit arguments for each python call."
)


def build_prompt_context(
    user_prompt: str,
    plan,
    python_call_outputs: list[dict],
    final_prompt: str,
    recalled_memories: str,
) -> dict:
    return {
        "original_user_prompt": user_prompt,
        "recalled_memories":    recalled_memories,
        "selected_skills":      [item.__dict__ for item in plan.selected_skills],
        "python_call_outputs":  python_call_outputs,
        "final_prompt_template": plan.final_prompt_template,
        "final_prompt":         final_prompt,
    }


# ====================================================================================================
# MARK: LOG FORMATTING HELPERS
# ====================================================================================================
def _format_plan_summary(plan, model_name: str) -> str:
    """Return a compact one-screen summary of the planner's decided execution plan."""
    lines: list[str] = []
    lines.append(f"Model : {model_name}")

    if plan.selected_skills:
        skill_names = [s.skill_name for s in plan.selected_skills]
        lines.append(f"Skills: {', '.join(skill_names)}")
    else:
        lines.append("Skills: (none selected)")

    if plan.python_calls:
        lines.append("")
        for call in sorted(plan.python_calls, key=lambda c: c.order):
            module_short = Path(call.module).stem
            lines.append(f"  [{call.order}] {module_short}.{call.function}()")
            for arg_name, arg_val in (call.arguments or {}).items():
                val_str = repr(arg_val)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."
                lines.append(f"       {arg_name} = {val_str}")
    else:
        lines.append("(no Python calls planned — LLM will answer directly)")

    if plan.final_prompt_template:
        tmpl = plan.final_prompt_template.strip()
        if len(tmpl) > 140:
            tmpl = tmpl[:137] + "..."
        lines.append(f"\nTemplate: {tmpl}")

    return "\n".join(lines)


def _format_skill_flow(python_call_outputs: list[dict]) -> str:
    """Return a compact structural summary of executed skill calls and their results."""
    if not python_call_outputs:
        return "(no skill calls were executed)"

    lines: list[str] = []
    for output in python_call_outputs:
        order    = output.get("order", "?")
        module   = Path(output.get("module", "")).stem
        function = output.get("function", "?")
        args     = output.get("arguments", {}) or {}
        result   = output.get("result")

        lines.append(f"[{order}] {module}.{function}()")

        for arg_name, arg_val in args.items():
            val_str = repr(arg_val)
            if len(val_str) > 120:
                val_str = val_str[:117] + "..."
            lines.append(f"     {arg_name} = {val_str}")

        if result is None:
            lines.append("     → None")
        elif isinstance(result, dict):
            keys = list(result.keys())
            lines.append(f"     → dict  [{', '.join(str(k) for k in keys)}]")
            for k, v in result.items():
                v_str = str(v).replace("\n", " ")
                if len(v_str) > 110:
                    v_str = v_str[:107] + "..."
                lines.append(f"          {k}: {v_str!r}")
        elif isinstance(result, list):
            lines.append(f"     → list  len={len(result)}")
            if result:
                first_str = str(result[0]).replace("\n", " ")
                if len(first_str) > 110:
                    first_str = first_str[:107] + "..."
                lines.append(f"          [0]: {first_str!r}")
        elif isinstance(result, str):
            result_stripped = result.strip()
            preview_lines   = result_stripped.splitlines()[:4]
            total_lines     = result_stripped.count("\n") + 1
            lines.append(f"     → str  {len(result)} chars / {total_lines} lines")
            for pl in preview_lines:
                if len(pl) > 110:
                    pl = pl[:107] + "..."
                lines.append(f"     {pl}")
            if total_lines > 4:
                lines.append(f"     ... ({total_lines - 4} more lines)")
        else:
            val_str = str(result)
            if len(val_str) > 110:
                val_str = val_str[:107] + "..."
            lines.append(f"     → {type(result).__name__}: {val_str}")

        lines.append("")

    return "\n".join(lines)


def _ordinal(n: int) -> str:
    """Return the English ordinal word for small integers (1→'first', 2→'second', …)."""
    _WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
              6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
    return _WORDS.get(n, str(n))


def build_final_llm_prompt(
    user_prompt: str,
    plan,
    python_call_outputs: list[dict],
    fallback_prompt: str,
    recalled_memories: str,
    ambient_system_info: str = "",
    conversation_history: list[dict] | None = None,
) -> str:
    call_outputs_json = json.dumps(python_call_outputs, indent=2)
    template_text     = (plan.final_prompt_template or "").strip()

    output_of_first_call = python_call_outputs[0]["result"] if python_call_outputs else ""
    output_of_last_call  = python_call_outputs[-1]["result"] if python_call_outputs else fallback_prompt

    if template_text:
        template_text = template_text.replace("{user_prompt}",             user_prompt)
        template_text = template_text.replace("{system_info}",             str(output_of_first_call))
        template_text = template_text.replace("{output_of_first_call}",    str(output_of_first_call))
        template_text = template_text.replace("{output_of_previous_call}", str(output_of_last_call))
        # Substitute {{outputN}} and {{output_of_Nth_call}} shorthand that the planner often emits.
        for idx, call_out in enumerate(python_call_outputs, start=1):
            val = str(call_out.get("result", ""))
            template_text = template_text.replace(f"{{{{output{idx}}}}}",              val)
            template_text = template_text.replace(f"{{{{output_of_{idx}_call}}}}",      val)
            template_text = template_text.replace(f"{{{{output_of_call_{idx}}}}}",      val)
            template_text = template_text.replace(f"{{{{output_of_{_ordinal(idx)}_call}}}}", val)

    history_section = ""
    if conversation_history:
        lines = [
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}"
            for t in conversation_history
        ]
        history_section = "Conversation history (most recent last):\n" + "\n".join(lines) + "\n\n"

    system_context_section = ""
    if ambient_system_info:
        system_context_section = (
            "Runtime system context (always available):\n"
            f"{ambient_system_info}\n\n"
        )

    return (
        "You are answering exactly one user question.\n"
        "Prioritize the user question over all other text.\n"
        "Answer directly and concisely without generic assistant filler.\n"
        "Never claim a tool action succeeded unless the Python skill outputs explicitly show success.\n"
        "Do not call any tools or functions. Respond with plain text only.\n"
        "\n"
        f"{history_section}"
        f"User question:\n{user_prompt}\n"
        "\n"
        f"{system_context_section}"
        "Python skill outputs (authoritative context):\n"
        f"{call_outputs_json}\n"
        "\n"
        "Relevant recalled memories (if any):\n"
        f"{recalled_memories}\n"
        "\n"
        "Planner template (optional guidance):\n"
        f"{template_text or 'N/A'}\n"
        "\n"
        "Return only the direct answer to the user question."
    )


# ====================================================================================================
# MARK: ORCHESTRATION PIPELINE
# ====================================================================================================
def orchestrate_prompt(
    user_prompt: str,
    config: OrchestratorConfig,
    logger: SessionLogger,
    conversation_history: list[dict] | None = None,
    quiet: bool = False,
) -> tuple[str, int, int, bool, float]:
    """Run the full planner -> skill -> LLM -> validate pipeline for one prompt.

    Returns (final_response, prompt_tokens, completion_tokens, run_success, tokens_per_second).

    When quiet=True, verbose orchestration stages are written to the log file only —
    the behaviour used in chat/dashboard/scheduler modes to keep output clean.
    """
    def _log(msg: str = "") -> None:
        logger.log_file_only(msg) if quiet else logger.log(msg)

    def _log_section(title: str) -> None:
        logger.log_section_file_only(title) if quiet else logger.log_section(title)

    # Always write to file only — used for verbose/bulk content that clutters stdout/console.
    def _log_file_only(msg: str = "") -> None:
        logger.log_file_only(msg)

    def _log_section_file_only(title: str) -> None:
        logger.log_section_file_only(title)

    user_prompt = resolve_tokens(user_prompt)

    _log_file_only("[progress] Storing prompt memories...")
    memory_store_result = store_prompt_memories(user_prompt=user_prompt)
    _log_file_only("[progress] Recalling relevant memories...")
    recalled_memories   = recall_relevant_memories(user_prompt=user_prompt, limit=5, min_score=0.2)
    planner_user_prompt = user_prompt
    if recalled_memories.startswith("Relevant memories:"):
        planner_user_prompt = f"{user_prompt}\n\nRecalled memory context:\n{recalled_memories}"

    _log_section("MEMORY")
    _log(memory_store_result)
    _log(recalled_memories)

    ambient_system_info = get_system_info_string()
    _log_section("AMBIENT SYSTEM INFO")
    _log(ambient_system_info)

    planner_feedback  = ""
    run_success       = False
    prompt_tokens     = 0
    completion_tokens = 0
    final_response    = ""
    final_tps         = 0.0

    for iteration in range(1, config.max_iterations + 1):
        _log_section_file_only(f"ITERATION {iteration} - PRE-PROCESSING PLAN")

        planner_ask = _PLANNER_ASK
        if planner_feedback:
            planner_ask = f"{_PLANNER_ASK} Previous iteration feedback: {planner_feedback}"

        _log_file_only(f"[progress] Iteration {iteration}: calling planner LLM ({config.resolved_model})...")
        plan, planner_prompt, planner_llm_result = create_skill_execution_plan(
            user_prompt=planner_user_prompt,
            skills_summary_path=_SKILLS_SUMMARY_PATH,
            planner_ask=planner_ask,
            model_name=config.resolved_model,
            num_ctx=config.num_ctx,
            skills_payload=config.skills_payload,
        )
        _log_file_only(f"[progress] Iteration {iteration}: planner complete.")

        _log_section(f"ITERATION {iteration} - SKILL PLAN")
        _log(_format_plan_summary(plan, config.resolved_model))

        # Full planner prompt — file only. Replace the static skills catalog block with a
        # path reference so the log contains only the dynamic, actionable parts.
        _log_section_file_only(f"ITERATION {iteration} - PRE-PROCESSING PLAN (verbose)")
        _skills_marker = "Skills summary context:\n"
        _marker_pos = planner_prompt.find(_skills_marker)
        if _marker_pos != -1:
            _logged_prompt = (
                planner_prompt[:_marker_pos + len(_skills_marker)]
                + f"[see {_SKILLS_SUMMARY_PATH}]"
            )
        else:
            _logged_prompt = planner_prompt
        _log_file_only(_logged_prompt)
        _log_section_file_only(f"ITERATION {iteration} - PRE-PROCESSING PLAN JSON (verbose)")
        _log_file_only(json.dumps(plan.to_dict(), indent=2))

        if planner_llm_result is not None:
            _log(f"Planner TPS: {planner_llm_result.tokens_per_second:.1f} tok/s"
                 f"  ({planner_llm_result.completion_tokens} tokens)")

        _log_section(f"ITERATION {iteration} - SKILL EXECUTION FLOW")
        _log_file_only(f"[progress] Iteration {iteration}: executing {len(plan.python_calls)} skill call(s)...")
        python_call_outputs, last_call_output = execute_skill_plan_calls(
            plan=plan,
            user_prompt=user_prompt,
            skills_payload=config.skills_payload,
        )
        _log_file_only(f"[progress] Iteration {iteration}: skill execution complete.")
        _log(_format_skill_flow(python_call_outputs))

        # Full outputs JSON (may contain large text/HTML payloads) — file only.
        _log_section_file_only(f"ITERATION {iteration} - PYTHON CALL OUTPUTS (verbose)")
        _log_file_only(json.dumps(python_call_outputs, indent=2))

        final_prompt = build_final_llm_prompt(
            user_prompt=user_prompt,
            plan=plan,
            python_call_outputs=python_call_outputs,
            fallback_prompt=last_call_output,
            recalled_memories=recalled_memories,
            ambient_system_info=ambient_system_info,
            conversation_history=conversation_history,
        )

        prompt_context = build_prompt_context(
            user_prompt=user_prompt,
            plan=plan,
            python_call_outputs=python_call_outputs,
            final_prompt=final_prompt,
            recalled_memories=recalled_memories,
        )

        _log_section_file_only(f"ITERATION {iteration} - PROMPT CONTEXT JSON (verbose)")
        _log_file_only(json.dumps(prompt_context, indent=2))

        _log_section(f"ITERATION {iteration} - FINAL LLM EXECUTION")

        if config.skip_final_llm:
            _log("[skip-final] Final LLM call skipped — returning skill output directly.")
            final_response    = last_call_output if isinstance(last_call_output, str) else str(last_call_output)
            run_success       = True
            break

        _log_file_only(f"[progress] Iteration {iteration}: calling final LLM ({config.resolved_model})...")
        try:
            result            = call_ollama_extended(model_name=config.resolved_model, prompt=final_prompt, num_ctx=config.num_ctx)
            final_response    = result.response.strip()
            prompt_tokens     = result.prompt_tokens
            completion_tokens = result.completion_tokens
            final_tps         = result.tokens_per_second
        except Exception as error:
            final_response   = ""
            planner_feedback = f"Final LLM execution failed: {error}"
            _log(planner_feedback)
            _log("Execution did not satisfy validation checks, retrying...")
            continue

        _log(final_response)
        _log(f"Final LLM TPS: {final_tps:.1f} tok/s  ({completion_tokens} tokens)")

        is_valid, validation_message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=python_call_outputs,
            final_prompt=final_prompt,
            final_response=final_response,
        )

        _log_section(f"ITERATION {iteration} - VALIDATION")
        _log(validation_message)

        if is_valid:
            run_success = True
            _log("Orchestration succeeded.")
            break

        planner_feedback = validation_message
        _log("Execution did not satisfy validation checks, retrying...")

    return final_response, prompt_tokens, completion_tokens, run_success, final_tps
