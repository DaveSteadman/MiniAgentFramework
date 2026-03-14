# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Builds and parses LLM-driven skill execution plans for the MiniAgentFramework.
#
# Defines the ExecutionPlan data model (SelectedSkill, PythonCall, ExecutionPlan), constructs the
# structured planner prompt from user input and the skills catalog, extracts and validates the JSON
# response returned by the LLM, and falls back to a deterministic DateTime-based plan when the LLM
# response cannot be parsed.
#
# Related modules:
#   - ollama_client.py          -- issues the LLM call inside create_skill_execution_plan
#   - skill_executor.py         -- consumes the ExecutionPlan produced here
#   - orchestration_validation.py -- validates the plan and its outputs
#   - main.py / preprocess_prompt.py -- entry points that call create_skill_execution_plan
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from ollama_client import call_ollama_extended
from ollama_client import OllamaCallResult


# ====================================================================================================
# MARK: DATA MODELS
# ====================================================================================================
@dataclass
class SelectedSkill:
    skill_name: str
    relative_path: str
    module: str
    reason: str


# ----------------------------------------------------------------------------------------------------
@dataclass
class PythonCall:
    order: int
    module: str
    function: str
    arguments: dict


# ----------------------------------------------------------------------------------------------------
@dataclass
class ExecutionPlan:
    user_prompt: str
    selected_skills: list[SelectedSkill]
    python_calls: list[PythonCall]
    final_prompt_template: str

    # ----------------------------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "user_prompt": self.user_prompt,
            "selected_skills": [asdict(item) for item in self.selected_skills],
            "python_calls": [asdict(item) for item in self.python_calls],
            "final_prompt_template": self.final_prompt_template,
        }


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_PLANNER_ASK = (
    "Given the user prompt, select needed skills and return python_calls JSON. "
    "Choose the minimum required skills and provide explicit arguments for each python call. "
    "CRITICAL RULE: one execution plan covers EXACTLY ONE pipeline stage. "
    "Never chain mining (WebMine) with analysis (WebResearchAnalysis) or presentation "
    "(WebResearchReport, WebResearchOutput) in the same plan unless the user prompt "
    "explicitly requests multiple stages in a single instruction. "
    "A prompt about researching, mining, or fetching web content means Stage 1 only. "
    "A prompt about analysing, summarising, or creating a report means Stage 2 only. "
    "A prompt about saving, rendering, or sending a report means Stage 3 only."
)


# ====================================================================================================
# MARK: JSON EXTRACTION + LOADING
# ====================================================================================================
def _repair_json_string_literals(text: str) -> str:
    """Escape unescaped control characters inside JSON string literals.

    LLMs sometimes emit multi-line code values with literal newlines rather than \\n
    escape sequences, producing invalid JSON.  This pass fixes those cases so that
    json.loads can succeed on an otherwise well-formed response.
    """
    result:      list[str] = []
    in_string:   bool      = False
    escape_next: bool      = False

    for char in text:
        if escape_next:
            result.append(char)
            escape_next = False
        elif in_string and char == "\\":
            result.append(char)
            escape_next = True
        elif char == '"':
            result.append(char)
            in_string = not in_string
        elif in_string:
            if char == "\n":
                result.append("\\n")
            elif char == "\r":
                result.append("\\r")
            elif char == "\t":
                result.append("\\t")
            else:
                result.append(char)
        else:
            result.append(char)

    return "".join(result)


def extract_first_json_object(text: str) -> str:
    start_index = text.find("{")
    if start_index < 0:
        raise RuntimeError("No JSON object found in provided text")

    # Walk the text character-by-character, tracking brace depth and string context.
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

    raise RuntimeError("Failed to parse complete JSON object from text")


# ----------------------------------------------------------------------------------------------------
def load_skills_payload(skills_summary_path: Path) -> dict:
    raw_text     = skills_summary_path.read_text(encoding="utf-8")
    json_segment = extract_first_json_object(raw_text)
    return json.loads(json_segment)


# ====================================================================================================
# MARK: PROMPT BUILDING
# ====================================================================================================
def build_planner_prompt(user_prompt: str, planner_ask: str, skills_payload: dict) -> str:
    skills_json = json.dumps(skills_payload, indent=2)

    return (
        "You are an orchestration planner.\n"
        "Use the provided skills summary context to decide which python calls should run.\n"
        "\n"
        f"Planner ask: {planner_ask}\n"
        f"User prompt: {user_prompt}\n"
        "\n"
        "Return ONLY one JSON object with this exact schema (no extra keys):\n"
        "{\n"
        '  "user_prompt": "string",\n'
        '  "selected_skills": [\n'
        "    {\n"
        '      "skill_name": "string",\n'
        '      "relative_path": "string",\n'
        '      "module": "string",\n'
        '      "reason": "string"\n'
        "    }\n"
        "  ],\n"
        '  "python_calls": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "module": "string",\n'
        '      "function": "string",\n'
        '      "arguments": {}\n'
        "    }\n"
        "  ],\n"
        '  "final_prompt_template": "string"\n'
        "}\n"
        "\n"
        "Rules:\n"
        "- Use only modules/functions that exist in the skills summary context.\n"
        "- Keep python_calls in execution order using integer order starting at 1.\n"
        "- Arguments must be a JSON object and must be explicit.\n"
        "- final_prompt_template should describe how outputs feed the next LLM prompt.\n"
        "\n"
        "Argument chaining - when a later call needs a value from an earlier call's output:\n"
        "  {{output_of_first_call}}         full result object of python_call order=1\n"
        "  {{output_of_previous_call}}      full result object of the immediately preceding call\n"
        "  ${output1.field}                 named field from call 1's result (e.g. ${output1.time})\n"
        "  ${output2.field}                 named field from call 2's result\n"
        "Example: DateTime returns {\"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM:SS\"}.\n"
        "  To append only the time: use \"text\": \"${output1.time}\" in the FileAccess call arguments.\n"
        "  To append the full datetime object: use \"text\": \"{{output_of_first_call}}\".\n"
        "NEVER use invented literal placeholders like 'time_placeholder' - always use the syntax above.\n"
        "\n"
        "Skills summary context:\n"
        f"{skills_json}"
    )


# ====================================================================================================
# MARK: PLAN PARSING + VALIDATION
# ====================================================================================================
def parse_execution_plan(plan_dict: dict) -> ExecutionPlan:
    required_keys = ["user_prompt", "selected_skills", "python_calls", "final_prompt_template"]
    missing = [key for key in required_keys if key not in plan_dict]
    if missing:
        raise RuntimeError(f"Planner JSON missing keys: {', '.join(missing)}")

    if not isinstance(plan_dict["selected_skills"], list):
        raise RuntimeError("selected_skills must be a list")
    if not isinstance(plan_dict["python_calls"], list):
        raise RuntimeError("python_calls must be a list")

    selected_skills = []
    for item in plan_dict["selected_skills"]:
        if not isinstance(item, dict):
            raise RuntimeError("Each selected_skills item must be an object")
        selected_skills.append(
            SelectedSkill(
                skill_name=str(item.get("skill_name", "")).strip(),
                relative_path=str(item.get("relative_path", "")).strip(),
                module=str(item.get("module", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )

    python_calls = []
    for item in plan_dict["python_calls"]:
        if not isinstance(item, dict):
            raise RuntimeError("Each python_calls item must be an object")
        for key in ["order", "module", "function", "arguments"]:
            if key not in item:
                raise RuntimeError(f"python_calls entry missing key: {key}")

        if not isinstance(item["arguments"], dict):
            raise RuntimeError("python_calls.arguments must be an object")

        python_calls.append(
            PythonCall(
                order=int(item["order"]),
                module=str(item["module"]),
                function=str(item["function"]),
                arguments=dict(item["arguments"]),
            )
        )

    # Sort calls by their declared order field so execution always follows the planner's sequence.
    python_calls.sort(key=lambda call: call.order)

    return ExecutionPlan(
        user_prompt=str(plan_dict["user_prompt"]),
        selected_skills=selected_skills,
        python_calls=python_calls,
        final_prompt_template=str(plan_dict["final_prompt_template"]),
    )


# ----------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------
# Deterministic skill-router used as a fallback when the LLM planner cannot produce a valid plan.
# Each entry maps a module filename fragment to a frozenset of trigger keywords extracted from the
# user prompt.  Evaluated in order; the first match with sufficient keyword overlap wins.
# These lists are heuristic only - they are NOT a source of truth for skill capabilities.
# The authoritative source remains the skills_summary catalog (skills_summary.md).
_SKILL_ROUTING: list[tuple[str, frozenset[str]]] = [
    ("system_info_skill.py",  frozenset({
        "system", "disk", "ram", "memory", "cpu", "storage", "space", "available",
        "free", "os", "operating", "platform", "python", "ollama", "runtime",
        "environment", "machine", "version", "health", "spec", "stat", "usage",
    })),
    ("code_execute_skill.py", frozenset({
        "calculate", "compute", "print", "list", "generate", "count", "sum",
        "fibonacci", "prime", "factorial", "sequence", "matrix", "sort",
        "average", "mean", "median", "mode", "convert", "binary", "hex",
        "octal", "table", "triangle", "palindrome", "power", "square", "cube",
        "multiply", "divide", "percentage", "compound", "interest", "collatz",
        "output", "number", "numbers", "integer", "integers",
    })),
    ("file_access_skill.py",  frozenset({
        "file", "write", "read", "append", "create", "save", "store",
        "csv", "txt", "open", "directory", "folder", "path",
    })),
    ("datetime_skill.py",     frozenset({
        "time", "date", "today", "yesterday", "now", "when", "clock", "current",
    })),
]

# Skills whose raw text output can be piped directly into a write_text_file call when the
# prompt mentions a file path.  Only used by the deterministic fallback planner.
_WRITE_SKILLS = frozenset({"system_info_skill.py", "code_execute_skill.py"})

# Lookup: fragment → table index (used for ordering).
_SKILL_PRIORITY = {frag: i for i, (frag, _) in enumerate(_SKILL_ROUTING)}

_PROMPT_PATH_RE = re.compile(
    r"(?<![\w./-])((?:\./)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:csv|txt|md|json|jsonl|log))(?![\w./-])",
    re.IGNORECASE,
)


def _skill_by_module_fragment(skills: list[dict], fragment: str) -> dict | None:
    for item in skills:
        if fragment in str(item.get("module", "")):
            return item
    return None


# ----------------------------------------------------------------------------------------------------
def _extract_path_from_prompt(user_prompt: str) -> str:
    path_match = _PROMPT_PATH_RE.search(user_prompt or "")
    if not path_match:
        return ""
    return path_match.group(1).strip().strip('"').strip("'")


def _select_skill_fragments(prompt_words: set[str], target_path: str) -> list[str]:
    """Score each skill by keyword overlap; return an ordered list of fragment names to use."""
    hits = {frag for frag, kw in _SKILL_ROUTING if prompt_words & kw}

    if not hits:
        return ["datetime_skill.py"]

    # datetime is the last-resort default; don't combine it with real skills.
    if len(hits) > 1:
        hits.discard("datetime_skill.py")

    # A compute skill + file skill only makes sense when there is a concrete target path.
    if "file_access_skill.py" in hits and hits & _WRITE_SKILLS and not target_path:
        hits.discard("file_access_skill.py")

    # Cap at two: the highest-priority compute skill plus optionally the file skill.
    ordered = sorted(hits, key=lambda f: _SKILL_PRIORITY.get(f, 99))
    if len(ordered) > 2:
        compute = [f for f in ordered if f != "file_access_skill.py"][:1]
        writer  = ["file_access_skill.py"] if "file_access_skill.py" in ordered else []
        ordered = compute + writer

    return ordered


def _make_fallback_call(
    order: int, fragment: str, module: str,
    user_prompt: str, target_path: str, is_chained: bool,
) -> "PythonCall":
    """Return a PythonCall for the given skill fragment, handling chained-write semantics."""
    if fragment == "system_info_skill.py":
        return PythonCall(order=order, module=module, function="get_system_info_string", arguments={})
    if fragment == "code_execute_skill.py":
        return PythonCall(order=order, module=module, function="run_python_snippet",
                          arguments={"code": "# LLM will supply code"})
    if fragment == "file_access_skill.py":
        if is_chained and target_path:
            return PythonCall(order=order, module=module, function="write_text_file",
                              arguments={"file_path": target_path, "text": "{{output_of_previous_call}}"})
        return PythonCall(order=order, module=module, function="execute_file_instruction",
                          arguments={"user_prompt": user_prompt})
    # datetime_skill.py and any unknown fragment
    return PythonCall(order=order, module=module, function="get_datetime_data", arguments={})


def _fallback_template(fragments: list[str]) -> str:
    has_code   = "code_execute_skill.py"  in fragments
    has_system = "system_info_skill.py"   in fragments
    has_file   = "file_access_skill.py"   in fragments
    if (has_code or has_system) and has_file:
        return "Compute the requested content, write it to the file, then confirm to the user."
    if has_code:
        return "Write and execute Python code to fulfil the user request. Return the code output as the answer."
    if has_system:
        return "Use the system info output to answer the user question directly."
    if has_file:
        return "Report the result of the file operation to the user."
    return "Return only the requested field from the date/time data."


def build_fallback_plan(user_prompt: str, skills_payload: dict) -> ExecutionPlan:
    skills      = skills_payload.get("skills", [])
    prompt_words = set(re.sub(r"[^a-z0-9 ]", " ", user_prompt.lower()).split())
    target_path = _extract_path_from_prompt(user_prompt)

    fragments = _select_skill_fragments(prompt_words, target_path)

    selected_skills: list[SelectedSkill] = []
    python_calls:    list[PythonCall]    = []

    for idx, frag in enumerate(fragments, start=1):
        skill = _skill_by_module_fragment(skills, frag)
        if skill is None:
            continue
        module     = str(skill.get("module", ""))
        is_chained = (frag == "file_access_skill.py") and (idx > 1) and bool(target_path)
        selected_skills.append(SelectedSkill(
            skill_name=str(skill.get("skill_name", frag)),
            relative_path=str(skill.get("relative_path", "")),
            module=module,
            reason=f"Fallback: {frag.replace('_skill.py', '')} selected by keyword match.",
        ))
        python_calls.append(_make_fallback_call(idx, frag, module, user_prompt, target_path, is_chained))

    if not python_calls:
        return ExecutionPlan(
            user_prompt=user_prompt, selected_skills=[], python_calls=[],
            final_prompt_template="No skills available in fallback plan.",
        )

    return ExecutionPlan(
        user_prompt=user_prompt,
        selected_skills=selected_skills,
        python_calls=python_calls,
        final_prompt_template=_fallback_template(fragments),
    )


# ----------------------------------------------------------------------------------------------------
def create_skill_execution_plan(
    user_prompt: str,
    skills_summary_path: Path,
    planner_ask: str,
    model_name: str,
    num_ctx: int,
    skills_payload: dict | None = None,
) -> tuple["ExecutionPlan", str, OllamaCallResult | None]:
    """Build a skill execution plan for the given prompt.

    Returns (plan, planner_prompt_text, planner_llm_result).  The planner_prompt_text is the
    exact text sent to the LLM so callers can log it.  planner_llm_result is the full
    OllamaCallResult (including TPS) or None when the fallback path was taken.

    If skills_payload is provided it is used as-is; otherwise it is loaded from
    skills_summary_path.  Callers that already hold the payload should pass it to
    avoid a redundant disk read on every orchestration iteration.
    """
    if skills_payload is None:
        skills_payload = load_skills_payload(skills_summary_path)

    planner_prompt = build_planner_prompt(
        user_prompt=user_prompt,
        planner_ask=planner_ask,
        skills_payload=skills_payload,
    )

    # Invoke LLM planner to propose skill calls in strict JSON shape.
    # If planner inference fails (timeout/network/server), fall back deterministically.
    try:
        planner_result = call_ollama_extended(model_name=model_name, prompt=planner_prompt, num_ctx=num_ctx)
        llm_text       = planner_result.response
    except Exception as exc:
        planner_prompt += f"\n[Planner LLM call failed: {exc}]"
        return build_fallback_plan(user_prompt=user_prompt, skills_payload=skills_payload), planner_prompt, None

    try:
        raw_json = extract_first_json_object(llm_text)
    except Exception:
        return build_fallback_plan(user_prompt=user_prompt, skills_payload=skills_payload), planner_prompt, planner_result

    # First attempt: parse as-is.  Second attempt: repair literal control chars in strings
    # (LLMs sometimes embed multi-line code with real newlines inside JSON string values).
    for json_candidate in (raw_json, _repair_json_string_literals(raw_json)):
        try:
            return parse_execution_plan(json.loads(json_candidate)), planner_prompt, planner_result
        except Exception:
            continue

    return build_fallback_plan(user_prompt=user_prompt, skills_payload=skills_payload), planner_prompt, planner_result
