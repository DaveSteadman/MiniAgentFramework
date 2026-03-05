# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Main orchestration entrypoint for the MiniAgentFramework.
#
# Supports two modes:
#   single-shot  Run one prompt through the full pipeline and exit (default).
#   chat         Interactive REPL: each turn runs the full pipeline; conversation history
#                is appended to the final prompt for multi-turn context.  Verbose
#                orchestration detail goes to the log file only; the console shows one
#                brief status line (context-token usage) and the LLM response per turn.
#
# Single-shot pipeline per prompt:
#   1. Resolves the configured LLM model alias to an installed Ollama model name.
#   2. Builds a structured skill execution plan via the planner (LLM-driven JSON).
#   3. Executes the approved Python skill calls and collects their outputs.
#   4. Constructs the final enriched prompt from outputs and the planner template.
#   5. Issues the final LLM call and validates the response.
#   6. Retries up to MAX_ITERATIONS times when validation fails, feeding back error context.
#
# Related modules:
#   - ollama_client.py              -- Ollama server management and LLM calls
#   - planner_engine.py             -- structured plan construction and parsing
#   - skill_executor.py             -- allow-listed skill call execution
#   - orchestration_validation.py   -- per-iteration output validation
#   - runtime_logger.py             -- session log file management
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from ollama_client import call_ollama_extended
from ollama_client import ensure_ollama_running
from ollama_client import format_running_model_report
from ollama_client import list_ollama_models
from ollama_client import resolve_model_name
from orchestration_validation import validate_orchestration_iteration
from planner_engine import create_skill_execution_plan
from planner_engine import load_skills_payload
from runtime_logger import create_log_file_path
from runtime_logger import SessionLogger
from skill_executor import execute_skill_plan_calls
from skills.Memory.memory_skill import recall_relevant_memories
from skills.Memory.memory_skill import store_prompt_memories
from skills.SystemInfo.system_info_skill import get_system_info_string


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
USER_PROMPT              = "output the time"
REQUESTED_MODEL          = "20b"
DEFAULT_NUM_CTX          = 32768
MAX_ITERATIONS           = 3
MAX_CHAT_HISTORY_TURNS   = 10     # keep the last N user/assistant pairs; older turns are trimmed
SKILLS_SUMMARY_PATH      = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
PLANNER_ASK              = (
    "Given the user prompt, select needed skills and return python_calls JSON. "
    "Choose the minimum required skills and provide explicit arguments for each python call."
)
LOG_DIR                  = Path(__file__).resolve().parent.parent / "logs"


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================
@dataclass
class OrchestratorConfig:
    """Immutable session-level configuration bundle.

    Passed through the orchestration layer so that adding new session-level settings
    requires only a change to this dataclass and the one place it is constructed in
    main() — not every intermediate function signature.
    """
    resolved_model: str
    num_ctx:        int
    max_iterations: int
    skills_payload: dict


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_main_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Main orchestration entrypoint.")
    parser.add_argument(
        "--user-prompt",
        type=str,
        default=USER_PROMPT,
        help="User prompt to orchestrate (single-shot mode only).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=REQUESTED_MODEL,
        help="Ollama model alias or tag to use (e.g. '20b', 'llama3:8b').",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help="Context window for planner and final LLM calls.",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        default=False,
        help="Start an interactive multi-turn chat session instead of a single-shot run.",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: ORCHESTRATION HELPERS
# ====================================================================================================
def resolve_execution_model(requested_model: str) -> str:
    available_models = list_ollama_models()
    if not available_models:
        raise RuntimeError("No models are installed in Ollama. Pull models first, then rerun.")

    resolved_model = resolve_model_name(requested_model, available_models)
    if resolved_model is None:
        available_text = ", ".join(available_models)
        raise RuntimeError(f"Model '{requested_model}' not installed. Available: {available_text}")

    return resolved_model


# ----------------------------------------------------------------------------------------------------
def build_prompt_context(
    user_prompt: str,
    plan,
    python_call_outputs: list[dict],
    final_prompt: str,
    recalled_memories: str,
) -> dict:
    return {
        "original_user_prompt": user_prompt,
        "recalled_memories": recalled_memories,
        "selected_skills": [item.__dict__ for item in plan.selected_skills],
        "python_call_outputs": python_call_outputs,
        "final_prompt_template": plan.final_prompt_template,
        "final_prompt": final_prompt,
    }


# ----------------------------------------------------------------------------------------------------
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

    # Extract convenience references to first and last skill call results.
    output_of_first_call = python_call_outputs[0]["result"] if python_call_outputs else ""
    output_of_last_call  = python_call_outputs[-1]["result"] if python_call_outputs else fallback_prompt

    # Substitute supported template placeholders with actual runtime values.
    if template_text:
        template_text = template_text.replace("{user_prompt}", user_prompt)
        template_text = template_text.replace("{system_info}", str(output_of_first_call))
        template_text = template_text.replace("{output_of_first_call}", str(output_of_first_call))
        template_text = template_text.replace("{output_of_previous_call}", str(output_of_last_call))

    # Build an optional conversation-history section for multi-turn chat context.
    history_section = ""
    if conversation_history:
        lines = [
            f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
            for turn in conversation_history
        ]
        history_section = "Conversation history (most recent last):\n" + "\n".join(lines) + "\n\n"

    # The ambient system context is always collected so the LLM can answer any runtime question
    # even when the planner did not explicitly select the SystemInfo skill.
    system_context_section = ""
    if ambient_system_info:
        system_context_section = (
            "Runtime system context (always available):\n"
            f"{ambient_system_info}\n"
            "\n"
        )

    return (
        "You are answering exactly one user question.\n"
        "Prioritize the user question over all other text.\n"
        "Answer directly and concisely without generic assistant filler.\n"
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
# MARK: ORCHESTRATION
# ====================================================================================================
def orchestrate_prompt(
    user_prompt: str,
    config: OrchestratorConfig,
    logger: SessionLogger,
    conversation_history: list[dict] | None = None,
    quiet: bool = False,
) -> tuple[str, int, int, bool]:
    """Run the full planner -> skill -> LLM pipeline for one prompt.

    Returns (final_response, prompt_tokens, completion_tokens, run_success, tokens_per_second).
    When quiet=True, verbose orchestration stages are written to the log file only,
    which is the behaviour used during chat mode to keep the console clean.
    """
    def _log(msg: str = "") -> None:
        logger.log_file_only(msg) if quiet else logger.log(msg)

    def _log_section(title: str) -> None:
        logger.log_section_file_only(title) if quiet else logger.log_section(title)

    memory_store_result = store_prompt_memories(user_prompt=user_prompt)
    recalled_memories   = recall_relevant_memories(user_prompt=user_prompt, limit=5, min_score=0.2)
    planner_user_prompt = user_prompt
    if recalled_memories.startswith("Relevant memories:"):
        planner_user_prompt = f"{user_prompt}\n\nRecalled memory context:\n{recalled_memories}"

    _log_section("MEMORY")
    _log(memory_store_result)
    _log(recalled_memories)

    # Collect system info unconditionally so every prompt has access to runtime context
    # regardless of whether the planner selected the SystemInfo skill.
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
        _log_section(f"ITERATION {iteration} - PRE-PROCESSING PLAN")

        iteration_planner_ask = PLANNER_ASK
        if planner_feedback:
            iteration_planner_ask = f"{PLANNER_ASK} Previous iteration feedback: {planner_feedback}"

        # create_skill_execution_plan returns (plan, planner_prompt_text, planner_llm_result).
        # Passing config.skills_payload avoids reloading the catalog from disk on every iteration.
        plan, planner_prompt, planner_llm_result = create_skill_execution_plan(
            user_prompt=planner_user_prompt,
            skills_summary_path=SKILLS_SUMMARY_PATH,
            planner_ask=iteration_planner_ask,
            model_name=config.resolved_model,
            num_ctx=config.num_ctx,
            skills_payload=config.skills_payload,
        )
        _log(planner_prompt)
        _log_section(f"ITERATION {iteration} - PRE-PROCESSING PLAN JSON")
        _log(json.dumps(plan.to_dict(), indent=2))
        if planner_llm_result is not None:
            planner_tps = planner_llm_result.tokens_per_second
            _log(f"Planner TPS: {planner_tps:.1f} tok/s  ({planner_llm_result.completion_tokens} tokens)")

        _log_section(f"ITERATION {iteration} - PYTHON CALL EXECUTION")
        # Execute allow-listed skill functions declared in the plan and collect outputs.
        python_call_outputs, last_call_output = execute_skill_plan_calls(
            plan=plan,
            user_prompt=user_prompt,
            skills_payload=config.skills_payload,
        )
        _log(json.dumps(python_call_outputs, indent=2))

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

        _log_section(f"ITERATION {iteration} - PROMPT CONTEXT JSON")
        _log(json.dumps(prompt_context, indent=2))

        _log_section(f"ITERATION {iteration} - FINAL LLM EXECUTION")
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

        # Gate iteration success on strict validation of skill usage and prompt completeness.
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


# ====================================================================================================
# MARK: CHAT MODE
# ====================================================================================================
def run_chat_mode(
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Interactive multi-turn chat loop. Each turn runs the full orchestration pipeline.

    Verbose orchestration detail (planner prompts, plan JSON, skill outputs, validation)
    is written to the log file only.  The console shows one brief status line with context-
    token usage and the LLM response per turn.

    Conversation history is capped at MAX_CHAT_HISTORY_TURNS pairs to prevent silent
    context overflow as the session grows.
    """
    conversation_history: list[dict] = []
    turn = 0

    print(f"\nChat mode active \u2014 model: {config.resolved_model} | num_ctx: {config.num_ctx:,}")
    print(f"Log file: {log_path.as_posix()}")
    print(f"History window: last {MAX_CHAT_HISTORY_TURNS} turns")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            user_prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nChat session ended.")
            break

        if not user_prompt:
            continue
        if user_prompt.lower() in {"exit", "quit"}:
            print("Chat session ended.")
            break

        turn += 1
        logger.log_section_file_only(f"CHAT TURN {turn}")
        logger.log_file_only(f"User prompt: {user_prompt}")

        final_response, prompt_tokens, completion_tokens, run_success, final_tps = orchestrate_prompt(
            user_prompt=user_prompt,
            config=config,
            logger=logger,
            conversation_history=conversation_history if conversation_history else None,
            quiet=True,
        )

        ctx_pct     = f"{prompt_tokens / config.num_ctx * 100:.1f}%" if config.num_ctx > 0 else "?"
        tps_str     = f" | {final_tps:.1f} tok/s" if final_tps > 0 else ""
        status_line = (
            f"[Turn {turn} | {prompt_tokens:,} / {config.num_ctx:,} ctx tokens ({ctx_pct}){tps_str} | {config.resolved_model}]"
        )
        print(status_line)

        if not run_success:
            print("(orchestration validation failed \u2014 response may be incomplete)")
            logger.log_file_only("Orchestration validation failed.")

        print(final_response)
        print()

        # Append this turn to the growing conversation history.
        conversation_history.append({"role": "user",      "content": user_prompt})
        conversation_history.append({"role": "assistant", "content": final_response})

        # Trim history to the rolling window to prevent context overflow.
        max_messages = MAX_CHAT_HISTORY_TURNS * 2
        if len(conversation_history) > max_messages:
            conversation_history = conversation_history[-max_messages:]
            print(f"(history trimmed to last {MAX_CHAT_HISTORY_TURNS} turns)")


# ====================================================================================================
# MARK: MAIN ENTRYPOINT
# ====================================================================================================
def main() -> None:
    args     = parse_main_args()
    log_path = create_log_file_path(log_dir=LOG_DIR)
    logger   = SessionLogger(log_path)

    # Ensure local Ollama server is ready before model discovery and LLM calls.
    ensure_ollama_running()
    # Resolve the requested model alias/tag into an installed concrete model name.
    resolved_model = resolve_execution_model(args.model)

    # Load the skills catalog once; it is passed through config so no module re-reads it.
    skills_payload = load_skills_payload(SKILLS_SUMMARY_PATH)

    config = OrchestratorConfig(
        resolved_model=resolved_model,
        num_ctx=args.num_ctx,
        max_iterations=MAX_ITERATIONS,
        skills_payload=skills_payload,
    )

    logger.log_section("SYSTEM STATUS")
    logger.log(f"Requested model: {args.model}")
    logger.log(f"Resolved model:  {resolved_model}")
    logger.log(f"Mode:            {'chat' if args.chat else 'single-shot'}")
    logger.log(f"num_ctx:         {args.num_ctx}")
    logger.log(f"Max iterations:  {MAX_ITERATIONS}")
    logger.log(format_running_model_report(resolved_model))
    logger.log(f"Log file:        {log_path.as_posix()}")

    if args.chat:
        run_chat_mode(config=config, logger=logger, log_path=log_path)
        return

    # Single-shot mode: orchestrate one prompt and validate.
    user_prompt = args.user_prompt
    logger.log(f"User prompt:     {user_prompt}")

    final_response, _, _, run_success, _ = orchestrate_prompt(
        user_prompt=user_prompt,
        config=config,
        logger=logger,
    )

    if not run_success:
        raise RuntimeError(
            f"Execution failed validation after {MAX_ITERATIONS} iterations. See log: {log_path.as_posix()}"
        )


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
