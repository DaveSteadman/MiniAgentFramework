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
    "What skills and python calls need to be executed in support of this user prompt? "
    "Return only structured JSON matching the requested schema."
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
        "Argument chaining — when a later call needs a value from an earlier call's output:\n"
        "  {{output_of_first_call}}         full result object of python_call order=1\n"
        "  {{output_of_previous_call}}      full result object of the immediately preceding call\n"
        "  ${output1.field}                 named field from call 1's result (e.g. ${output1.time})\n"
        "  ${output2.field}                 named field from call 2's result\n"
        "Example: DateTime returns {\"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM:SS\"}.\n"
        "  To append only the time: use \"text\": \"${output1.time}\" in the FileAccess call arguments.\n"
        "  To append the full datetime object: use \"text\": \"{{output_of_first_call}}\".\n"
        "NEVER use invented literal placeholders like 'time_placeholder' — always use the syntax above.\n"
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
_FALLBACK_SYSTEM_KEYWORDS = frozenset({
    "system", "disk", "ram", "memory", "cpu", "storage", "space", "available",
    "free", "os", "operating", "platform", "python", "ollama", "runtime",
    "environment", "machine", "version", "health", "spec", "stat", "usage",
})
_FALLBACK_FILE_KEYWORDS = frozenset({
    "file", "write", "read", "append", "create", "save", "store",
    "csv", "txt", "open", "directory", "folder", "path",
})
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


def build_fallback_plan(user_prompt: str, skills_payload: dict) -> ExecutionPlan:
    skills       = skills_payload.get("skills", [])
    prompt_lower = user_prompt.lower()
    prompt_words = set(prompt_lower.replace("?", " ").replace(",", " ").split())
    target_path  = _extract_path_from_prompt(user_prompt)

    # Pick skill based on keyword presence in the user prompt.
    has_system_keyword = bool(prompt_words & _FALLBACK_SYSTEM_KEYWORDS)
    has_file_keyword   = bool(prompt_words & _FALLBACK_FILE_KEYWORDS)

    if has_system_keyword and has_file_keyword and target_path:
        system_skill = _skill_by_module_fragment(skills, "system_info_skill.py")
        file_skill   = _skill_by_module_fragment(skills, "file_access_skill.py")
        if system_skill is not None and file_skill is not None:
            system_module = str(system_skill.get("module", ""))
            file_module   = str(file_skill.get("module", ""))
            return ExecutionPlan(
                user_prompt=user_prompt,
                selected_skills=[
                    SelectedSkill(
                        skill_name=str(system_skill.get("skill_name", "SystemInfo Skill")),
                        relative_path=str(system_skill.get("relative_path", "")),
                        module=system_module,
                        reason="Fallback: system/resource keywords detected in prompt.",
                    ),
                    SelectedSkill(
                        skill_name=str(file_skill.get("skill_name", "FileAccess Skill")),
                        relative_path=str(file_skill.get("relative_path", "")),
                        module=file_module,
                        reason="Fallback: file output keywords detected in prompt.",
                    ),
                ],
                python_calls=[
                    PythonCall(order=1, module=system_module, function="get_system_info_string", arguments={}),
                    PythonCall(
                        order=2,
                        module=file_module,
                        function="write_text_file",
                        arguments={
                            "file_path": target_path,
                            "text": "{{output_of_previous_call}}",
                        },
                    ),
                ],
                final_prompt_template="Report the file write result to the user using the FileAccess output.",
            )

    if has_system_keyword and not has_file_keyword:
        skill = _skill_by_module_fragment(skills, "system_info_skill.py")
        if skill is not None:
            module = str(skill.get("module", ""))
            return ExecutionPlan(
                user_prompt=user_prompt,
                selected_skills=[
                    SelectedSkill(
                        skill_name=str(skill.get("skill_name", "SystemInfo Skill")),
                        relative_path=str(skill.get("relative_path", "")),
                        module=module,
                        reason="Fallback: system/resource keywords detected in prompt.",
                    )
                ],
                python_calls=[
                    PythonCall(order=1, module=module, function="get_system_info_string", arguments={})
                ],
                final_prompt_template="Use the system info output to answer the user question directly.",
            )

    if has_file_keyword:
        skill = _skill_by_module_fragment(skills, "file_access_skill.py")
        if skill is not None:
            module = str(skill.get("module", ""))
            return ExecutionPlan(
                user_prompt=user_prompt,
                selected_skills=[
                    SelectedSkill(
                        skill_name=str(skill.get("skill_name", "FileAccess Skill")),
                        relative_path=str(skill.get("relative_path", "")),
                        module=module,
                        reason="Fallback: file operation keywords detected in prompt.",
                    )
                ],
                python_calls=[
                    PythonCall(
                        order=1,
                        module=module,
                        function="execute_file_instruction",
                        arguments={"user_prompt": user_prompt},
                    )
                ],
                final_prompt_template="Report the result of the file operation to the user.",
            )

    # Default: DateTime (temporal questions or when no keywords matched).
    skill = _skill_by_module_fragment(skills, "datetime_skill.py")
    if skill is not None:
        module = str(skill.get("module", ""))
        return ExecutionPlan(
            user_prompt=user_prompt,
            selected_skills=[
                SelectedSkill(
                    skill_name=str(skill.get("skill_name", "DateTime Skill")),
                    relative_path=str(skill.get("relative_path", "")),
                    module=module,
                    reason="Fallback: default DateTime skill.",
                )
            ],
            python_calls=[
                PythonCall(order=1, module=module, function="get_datetime_data", arguments={})
            ],
            final_prompt_template="Return only the requested field from the date/time data.",
        )

    return ExecutionPlan(
        user_prompt=user_prompt,
        selected_skills=[],
        python_calls=[],
        final_prompt_template="No skills selected in fallback plan.",
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
