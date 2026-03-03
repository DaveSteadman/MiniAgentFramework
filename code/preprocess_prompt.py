# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import json
from pathlib import Path

from ollama_client import ensure_ollama_running
from planner_engine import DEFAULT_PLANNER_ASK
from planner_engine import create_skill_execution_plan


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_MODEL          = "gpt-oss:20b"
DEFAULT_NUM_CTX        = 32768
DEFAULT_SKILLS_SUMMARY = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
DEFAULT_OUTPUT_PLAN    = Path(__file__).resolve().parent / "skills" / "skills_plan.json"


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_preprocess_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-process user prompt into executable Python call plan.")
    parser.add_argument("--user-prompt", required=True, help="Raw user prompt text to plan against.")
    parser.add_argument("--skills-summary", default=str(DEFAULT_SKILLS_SUMMARY), help="Path to skills_summary.md file.")
    parser.add_argument("--planner-ask", default=DEFAULT_PLANNER_ASK, help="Instruction for the planning LLM call.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model for planning.")
    parser.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX, help="Context window for planning LLM call.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PLAN), help="Path to write structured JSON plan.")
    parser.add_argument("--print-only", action="store_true", help="Print plan JSON and skip writing output file.")
    return parser.parse_args()


# ----------------------------------------------------------------------------------------------------
def main() -> None:
    args = parse_preprocess_args()

    skills_summary_path = Path(args.skills_summary).resolve()
    output_path         = Path(args.output).resolve()

    ensure_ollama_running()

    # One-line comment: Ask planner for structured skill execution plan using shared typed engine.
    plan = create_skill_execution_plan(
        user_prompt=args.user_prompt,
        skills_summary_path=skills_summary_path,
        planner_ask=args.planner_ask,
        model_name=args.model,
        num_ctx=args.num_ctx,
    )

    plan_text = json.dumps(plan.to_dict(), indent=2)

    if args.print_only:
        print(plan_text)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(plan_text, encoding="utf-8")
    print(f"Wrote execution plan: {output_path.as_posix()}")


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
