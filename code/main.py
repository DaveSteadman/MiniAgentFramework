# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import json
from pathlib import Path

from ollama_client import call_ollama
from ollama_client import ensure_ollama_running
from ollama_client import format_running_model_report
from ollama_client import list_ollama_models
from ollama_client import resolve_model_name
from orchestration_validation import validate_orchestration_iteration
from planner_engine import build_planner_prompt
from planner_engine import create_skill_execution_plan
from planner_engine import load_skills_payload
from runtime_logger import create_log_file_path
from runtime_logger import SessionLogger
from skill_executor import execute_skill_plan_calls


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
USER_PROMPT         = "output the time"
REQUESTED_MODEL     = "20b"
DEFAULT_NUM_CTX     = 32768
MAX_ITERATIONS      = 3
SKILLS_SUMMARY_PATH = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
PLANNER_ASK         = (
    "Given the user prompt, select needed skills and return python_calls JSON. "
    "Choose the minimum required skills and provide explicit arguments for each python call."
)
LOG_DIR             = Path(__file__).resolve().parent.parent / "logs"


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_main_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Main orchestration entrypoint.")
    parser.add_argument(
        "--user-prompt",
        type=str,
        default=USER_PROMPT,
        help="User prompt to orchestrate.",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help="Context window for planner and final LLM calls.",
    )
    return parser.parse_args()


# ====================================================================================================
# MARK: ORCHESTRATION HELPERS
# ====================================================================================================
def resolve_execution_model() -> str:
    available_models = list_ollama_models()
    if not available_models:
        raise RuntimeError("No models are installed in Ollama. Pull models first, then rerun.")

    resolved_model = resolve_model_name(REQUESTED_MODEL, available_models)
    if resolved_model is None:
        available_text = ", ".join(available_models)
        raise RuntimeError(f"Model '{REQUESTED_MODEL}' not installed. Available: {available_text}")

    return resolved_model


# ----------------------------------------------------------------------------------------------------
def build_prompt_context(user_prompt: str, plan, python_call_outputs: list[dict], final_prompt: str) -> dict:
    return {
        "original_user_prompt": user_prompt,
        "selected_skills": [item.__dict__ for item in plan.selected_skills],
        "python_call_outputs": python_call_outputs,
        "final_prompt_template": plan.final_prompt_template,
        "final_prompt": final_prompt,
    }


# ----------------------------------------------------------------------------------------------------
def build_final_llm_prompt(user_prompt: str, plan, python_call_outputs: list[dict], fallback_prompt: str) -> str:
    call_outputs_json = json.dumps(python_call_outputs, indent=2)
    template_text     = (plan.final_prompt_template or "").strip()

    output_of_first_call = python_call_outputs[0]["result"] if python_call_outputs else ""
    output_of_last_call  = python_call_outputs[-1]["result"] if python_call_outputs else fallback_prompt

    if template_text:
        template_text = template_text.replace("{user_prompt}", user_prompt)
        template_text = template_text.replace("{system_info}", str(output_of_first_call))
        template_text = template_text.replace("{output_of_first_call}", str(output_of_first_call))
        template_text = template_text.replace("{output_of_previous_call}", str(output_of_last_call))

    return (
        "You are answering exactly one user question.\n"
        "Prioritize the user question over all other text.\n"
        "Answer directly and concisely without generic assistant filler.\n"
        "\n"
        f"User question:\n{user_prompt}\n"
        "\n"
        "Python skill outputs (authoritative context):\n"
        f"{call_outputs_json}\n"
        "\n"
        "Planner template (optional guidance):\n"
        f"{template_text or 'N/A'}\n"
        "\n"
        "Return only the direct answer to the user question."
    )


# ====================================================================================================
# MARK: MAIN ENTRYPOINT
# ====================================================================================================
def main() -> None:
    args       = parse_main_args()
    user_prompt = args.user_prompt
    log_path   = create_log_file_path(log_dir=LOG_DIR)
    logger     = SessionLogger(log_path)

    # One-line comment: Ensure local Ollama server is ready before model discovery and LLM calls.
    ensure_ollama_running()
    # One-line comment: Resolve configured model alias/tag into an installed concrete model name.
    resolved_model = resolve_execution_model()

    logger.log_section("SYSTEM STATUS")
    logger.log(f"Requested model: {REQUESTED_MODEL}")
    logger.log(f"Resolved model:  {resolved_model}")
    logger.log(f"User prompt:     {user_prompt}")
    logger.log(f"num_ctx:         {args.num_ctx}")
    logger.log(f"Max iterations:  {MAX_ITERATIONS}")
    logger.log(format_running_model_report(resolved_model))
    logger.log(f"Log file:        {log_path.as_posix()}")

    skills_payload = load_skills_payload(SKILLS_SUMMARY_PATH)
    planner_feedback = ""
    run_success = False

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.log_section(f"ITERATION {iteration} - PRE-PROCESSING PROMPT")

        iteration_planner_ask = PLANNER_ASK
        if planner_feedback:
            iteration_planner_ask = f"{PLANNER_ASK} Previous iteration feedback: {planner_feedback}"

        planner_prompt = build_planner_prompt(
            user_prompt=user_prompt,
            planner_ask=iteration_planner_ask,
            skills_payload=skills_payload,
        )
        logger.log(planner_prompt)

        logger.log_section(f"ITERATION {iteration} - PRE-PROCESSING PLAN JSON")
        # One-line comment: Request structured JSON execution plan from LLM planner (with fallback inside planner engine).
        plan = create_skill_execution_plan(
            user_prompt=user_prompt,
            skills_summary_path=SKILLS_SUMMARY_PATH,
            planner_ask=iteration_planner_ask,
            model_name=resolved_model,
            num_ctx=args.num_ctx,
        )
        logger.log(json.dumps(plan.to_dict(), indent=2))

        logger.log_section(f"ITERATION {iteration} - PYTHON CALL EXECUTION")
        # One-line comment: Execute allow-listed skill functions declared in the plan and collect outputs.
        python_call_outputs, fallback_prompt = execute_skill_plan_calls(
            plan=plan,
            user_prompt=user_prompt,
            skills_payload=skills_payload,
        )
        logger.log(json.dumps(python_call_outputs, indent=2))

        final_prompt = build_final_llm_prompt(
            user_prompt=user_prompt,
            plan=plan,
            python_call_outputs=python_call_outputs,
            fallback_prompt=fallback_prompt,
        )

        prompt_context = build_prompt_context(
            user_prompt=user_prompt,
            plan=plan,
            python_call_outputs=python_call_outputs,
            final_prompt=final_prompt,
        )

        logger.log_section(f"ITERATION {iteration} - PROMPT CONTEXT JSON")
        logger.log(json.dumps(prompt_context, indent=2))

        logger.log_section(f"ITERATION {iteration} - FINAL LLM EXECUTION")
        final_response = call_ollama(model_name=resolved_model, prompt=final_prompt, num_ctx=args.num_ctx).strip()
        logger.log(final_response)

        # One-line comment: Gate iteration success on strict validation of skill usage and visible time output.
        is_valid, validation_message = validate_orchestration_iteration(
            plan=plan,
            python_call_outputs=python_call_outputs,
            final_prompt=final_prompt,
            final_response=final_response,
        )

        logger.log_section(f"ITERATION {iteration} - VALIDATION")
        logger.log(validation_message)

        if is_valid:
            run_success = True
            logger.log("Execution succeeded with valid output time.")
            break

        planner_feedback = validation_message
        logger.log("Execution did not satisfy validation checks, retrying...")

    if not run_success:
        raise RuntimeError(f"Execution failed validation after {MAX_ITERATIONS} iterations. See log: {log_path.as_posix()}")


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
