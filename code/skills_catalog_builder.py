# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Discovers all skill.md definition files and builds a consolidated JSON catalog for orchestration.
#
# Scans the skills directory recursively for skill.md files, summarises each one into a structured
# JSON record (skill name, module path, functions, inputs, outputs), then writes the full catalog
# as a single skills_summary.md file. The planner engine reads this summary at runtime to decide
# which skill calls to include in an execution plan.
#
# Supports two summarisation modes:
#   - LLM-assisted: sends the skill.md text to an Ollama model and parses the JSON response.
#   - Local (--no-llm): deterministic regex/text extraction, used as a fallback or for CI.
#
# Usage:
#   python skills_catalog_builder.py
#   python skills_catalog_builder.py --no-llm
#   python skills_catalog_builder.py --skills-root /path/to/skills --output /path/to/output.md
#
# Related modules:
#   - ollama_client.py    -- used for optional LLM-assisted summarisation
#   - planner_engine.py   -- consumes the skills_summary.md produced here
#   - MiniAgentFramework.py -- top-level entrypoint that calls main() in this module
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import json
import re
from pathlib import Path

from ollama_client import call_ollama
from ollama_client import ensure_ollama_running


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
SKILLS_SCHEMA_VERSION = "1.0"
DEFAULT_SKILLS_ROOT   = Path(__file__).resolve().parent / "skills"
DEFAULT_OUTPUT_FILE   = DEFAULT_SKILLS_ROOT / "skills_summary.md"
DEFAULT_SUMMARY_MODEL = "gpt-oss:20b"


# ====================================================================================================
# MARK: CLI
# ====================================================================================================
def parse_catalog_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build JSON summary catalog for all skills.")
    parser.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT), help="Root folder containing skills.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="Output markdown summary file.")
    parser.add_argument("--model", default=DEFAULT_SUMMARY_MODEL, help="Ollama model used for LLM summarization.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM calls and use local deterministic extraction only.",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=32768,
        help="Context window for summary LLM calls (ignored with --no-llm).",
    )
    return parser.parse_args()


# ----------------------------------------------------------------------------------------------------
def find_skill_files(skills_root: Path) -> list[Path]:
    return sorted(skills_root.rglob("skill.md"))


# ----------------------------------------------------------------------------------------------------
def extract_json_block(text: str) -> dict | None:
    first_object_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not first_object_match:
        return None

    try:
        return json.loads(first_object_match.group(0))
    except json.JSONDecodeError:
        return None


# ----------------------------------------------------------------------------------------------------
def summarize_with_llm(skill_md_path: Path, model_name: str, num_ctx: int) -> dict | None:
    skill_text = skill_md_path.read_text(encoding="utf-8")

    prompt = (
        "You are summarizing a software skill definition file.\n"
        "Return ONLY a single JSON object with this schema and no extra keys:\n"
        "{\n"
        '  "skill_name": "string",\n'
        '  "relative_path": "string",\n'
        '  "purpose": "string",\n'
        '  "module": "string",\n'
        '  "functions": ["string"],\n'
        '  "inputs": ["string"],\n'
        '  "outputs": ["string"]\n'
        "}\n"
        f"relative_path must be exactly: {skill_md_path.as_posix()}\n"
        "If any section is missing, infer conservatively from the file text.\n"
        "Skill file text:\n"
        f"{skill_text}"
    )

    llm_response = call_ollama(model_name=model_name, prompt=prompt, num_ctx=num_ctx)
    return extract_json_block(llm_response)


# ----------------------------------------------------------------------------------------------------
def summarize_locally(skill_md_path: Path) -> dict:
    skill_text = skill_md_path.read_text(encoding="utf-8")
    lines      = [line.strip() for line in skill_text.splitlines() if line.strip()]

    # Use the first Markdown heading as the skill title, falling back to the parent directory name.
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), skill_md_path.parent.name)
    purpose = ""
    for index, line in enumerate(lines):
        if line.lower().startswith("## purpose") and index + 1 < len(lines):
            purpose = lines[index + 1]
            break

    # Extract the module path from a backtick-quoted "Module:" field in the file.
    module = ""
    module_match = re.search(r"-\s*Module:\s*`([^`]+)`", skill_text)
    if module_match:
        module = module_match.group(1)

    # Collect all backtick-quoted function signatures (e.g. `func_name(args)`).
    functions = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*\([^`]*\))`", skill_text)

    # Extract bullet-point items from the Input and Output sections.
    input_section = re.findall(r"## Input(.*?)(##|$)", skill_text, re.DOTALL | re.IGNORECASE)
    output_section = re.findall(r"## Output(.*?)(##|$)", skill_text, re.DOTALL | re.IGNORECASE)

    input_lines = []
    if input_section:
        input_lines = [line.strip(" -") for line in input_section[0][0].splitlines() if line.strip().startswith("-")]

    output_lines = []
    if output_section:
        output_lines = [line.strip(" -") for line in output_section[0][0].splitlines() if line.strip().startswith("-")]

    return {
        "skill_name": title,
        "relative_path": skill_md_path.as_posix(),
        "purpose": purpose,
        "module": module,
        "functions": sorted(set(functions)),
        "inputs": input_lines,
        "outputs": output_lines,
    }


# ----------------------------------------------------------------------------------------------------
def summarize_skill(skill_md_path: Path, use_llm: bool, model_name: str, num_ctx: int) -> dict:
    if use_llm:
        try:
            llm_summary = summarize_with_llm(skill_md_path=skill_md_path, model_name=model_name, num_ctx=num_ctx)
            if isinstance(llm_summary, dict):
                return llm_summary
        except Exception:
            pass

    return summarize_locally(skill_md_path=skill_md_path)


# ----------------------------------------------------------------------------------------------------
def to_workspace_relative_path(path: Path) -> str:
    workspace_root = Path(__file__).resolve().parent.parent
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ----------------------------------------------------------------------------------------------------
def normalize_summary(summary: dict, skill_md_path: Path) -> dict:
    normalized = dict(summary)
    normalized["relative_path"] = to_workspace_relative_path(skill_md_path)

    for field_name in ["functions", "inputs", "outputs"]:
        field_value = normalized.get(field_name, [])
        if isinstance(field_value, list):
            normalized[field_name] = [str(item).strip() for item in field_value if str(item).strip()]
        elif isinstance(field_value, str) and field_value.strip():
            normalized[field_name] = [field_value.strip()]
        else:
            normalized[field_name] = []

    return normalized


# ----------------------------------------------------------------------------------------------------
def render_summary_document(summaries: list[dict], output_path: Path) -> str:
    payload = {
        "schema_version": SKILLS_SCHEMA_VERSION,
        "skills_root": to_workspace_relative_path(output_path.parent),
        "skills": summaries,
    }

    return "\n".join(
        [
            "# Skills Summary",
            "",
            "Single JSON payload for orchestration planning.",
            "",
            json.dumps(payload, indent=2),
            "",
        ]
    )


# ----------------------------------------------------------------------------------------------------
def main() -> None:
    args        = parse_catalog_args()
    skills_root = Path(args.skills_root).resolve()
    output_path = Path(args.output).resolve()

    skill_files = find_skill_files(skills_root=skills_root)
    if not skill_files:
        raise RuntimeError(f"No skill.md files found under {skills_root}")

    if not args.no_llm:
        ensure_ollama_running()

    summaries = []
    for skill_file in skill_files:
        relative_skill_file = to_workspace_relative_path(skill_file)
        print(f"Summarizing {relative_skill_file}...")

        # Use LLM summary when available, with deterministic local fallback for robustness.
        summary = summarize_skill(
            skill_md_path=skill_file,
            use_llm=not args.no_llm,
            model_name=args.model,
            num_ctx=args.num_ctx,
        )
        summaries.append(normalize_summary(summary=summary, skill_md_path=skill_file))

    summary_text = render_summary_document(summaries=summaries, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary_text, encoding="utf-8")

    print(f"Wrote {to_workspace_relative_path(output_path)} with {len(summaries)} skill summaries.")


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
