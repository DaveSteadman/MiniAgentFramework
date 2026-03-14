# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Discovers all skill.md definition files and builds a consolidated JSON catalog for orchestration.
#
# Scans the skills directory recursively for skill.md files, summarises each one into a structured
# JSON record (skill name, module path, functions, inputs, outputs), then writes the full catalog
# as a single skills_summary.md file. The orchestration layer uses this catalog to build
# JSON Schema tool definitions sent to the model via /v1/chat/completions.
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
#   - orchestration.py    -- calls build_tool_definitions at runtime; consumes the catalog
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
        default=131072,
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
        if re.match(r"^##\s+(purpose|overview)$", line, re.IGNORECASE) and index + 1 < len(lines):
            purpose = lines[index + 1]
            break

    # Extract the module path. Handles two formats:
    #   - Bullet:  "- Module: `path`"
    #   - Heading: "## Module\n`path`"
    module = ""
    module_match = re.search(r"-\s*Module:\s*`([^`]+)`", skill_text)
    if module_match:
        module = module_match.group(1)
    else:
        heading_match = re.search(r"##\s+Module\s*\n+`([^`]+)`", skill_text)
        if heading_match:
            module = heading_match.group(1)

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


# ====================================================================================================
# MARK: CATALOG LOADING
# ====================================================================================================
def extract_first_json_object(text: str) -> str:
    """Extract the first complete JSON object from *text*, raising RuntimeError if none found."""
    start_index = text.find("{")
    if start_index < 0:
        raise RuntimeError("No JSON object found in provided text")

    depth     = 0
    in_string = False
    escaped   = False

    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]

    raise RuntimeError("Failed to parse a complete JSON object from text")


# ----------------------------------------------------------------------------------------------------
def _rebuild_skills_catalog_if_stale(skills_summary_path: Path) -> None:
    """Rebuild skills_summary.md when any skill.md is newer than the summary (no-LLM fast path)."""
    skills_root = skills_summary_path.parent
    if not skills_summary_path.exists():
        needs_rebuild = True
    else:
        summary_mtime = skills_summary_path.stat().st_mtime
        skill_files   = list(skills_root.rglob("skill.md"))
        needs_rebuild = any(sf.stat().st_mtime > summary_mtime for sf in skill_files)

    if not needs_rebuild:
        return

    skill_files  = find_skill_files(skills_root)
    summaries    = [
        normalize_summary(
            summarize_skill(sf, use_llm=False, model_name="", num_ctx=0),
            sf,
        )
        for sf in skill_files
    ]
    summary_text = render_summary_document(summaries, skills_summary_path)
    skills_summary_path.parent.mkdir(parents=True, exist_ok=True)
    skills_summary_path.write_text(summary_text, encoding="utf-8")


# ----------------------------------------------------------------------------------------------------
def load_skills_payload(skills_summary_path: Path) -> dict:
    """Load the skills catalog JSON from *skills_summary_path*, rebuilding it if stale."""
    _rebuild_skills_catalog_if_stale(skills_summary_path)
    raw_text     = skills_summary_path.read_text(encoding="utf-8")
    json_segment = extract_first_json_object(raw_text)
    return json.loads(json_segment)


# ====================================================================================================
# MARK: TOOL DEFINITIONS
# ====================================================================================================
_CLEAN_SIG_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\(([^"<>\\]*)\)$')
_PARAM_RE     = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([A-Za-z_][A-Za-z0-9_\[\]| ]*))?\s*(?:=\s*\S+)?')


def _python_type_to_json_type(ptype: str) -> str:
    ptype_lower = ptype.lower().strip()
    if ptype_lower in ("bool", "boolean"):
        return "boolean"
    if ptype_lower in ("int", "float", "number"):
        return "number"
    return "string"


def _parse_tool_signature(sig: str) -> tuple[str, list[dict]] | None:
    """Parse 'func_name(p1: type1, p2: type2)' into (name, params_list).

    Returns None when the signature looks like an example call (contains quotes, <>, or backslashes).
    """
    m = _CLEAN_SIG_RE.match(sig.strip())
    if not m:
        return None
    func_name  = m.group(1)
    params_str = m.group(2).strip()

    params: list[dict] = []
    if params_str:
        for part in params_str.split(","):
            part = part.strip()
            if not part:
                continue
            pm = _PARAM_RE.match(part)
            if not pm:
                continue
            pname       = pm.group(1).strip()
            ptype       = (pm.group(2) or "str").strip()
            has_default = "=" in part
            params.append({"name": pname, "type": ptype, "required": not has_default})

    return func_name, params


def build_tool_definitions(skills_payload: dict) -> list[dict]:
    """Convert the skills catalog payload into OpenAI-format JSON Schema tool definitions.

    Each clean function signature (e.g. 'get_datetime_data()' or 'set_task_prompt(name: str, ...)')
    becomes one tool entry. Example-call entries in the functions list are silently skipped.
    Compatible with Ollama /v1/chat/completions, LM Studio, and OpenAI.
    """
    tools:      list[dict] = []
    seen_names: set[str]   = set()

    for skill in skills_payload.get("skills", []):
        purpose = skill.get("purpose", "")
        module  = skill.get("module", "")

        for func_sig in skill.get("functions", []):
            parsed = _parse_tool_signature(func_sig)
            if parsed is None:
                continue
            func_name, params = parsed
            if func_name in seen_names:
                continue
            seen_names.add(func_name)

            properties: dict = {}
            required:   list = []
            for p in params:
                properties[p["name"]] = {
                    "type":        _python_type_to_json_type(p["type"]),
                    "description": p["name"],
                }
                if p["required"]:
                    required.append(p["name"])

            tool_func: dict = {
                "name":        func_name,
                "description": f"{purpose}  [module: {Path(module).stem}]",
                "parameters": {
                    "type":       "object",
                    "properties": properties,
                },
            }
            if required:
                tool_func["parameters"]["required"] = required

            tools.append({"type": "function", "function": tool_func})

    return tools


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
