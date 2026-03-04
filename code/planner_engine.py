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
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from ollama_client import call_ollama


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
def build_fallback_plan(user_prompt: str, skills_payload: dict) -> ExecutionPlan:
    skills = skills_payload.get("skills", [])

    datetime_skill = None
    for item in skills:
        module_value = str(item.get("module", ""))
        if "datetime_skill.py" in module_value:
            datetime_skill = item
            break

    if datetime_skill is not None:
        return ExecutionPlan(
            user_prompt=user_prompt,
            selected_skills=[
                SelectedSkill(
                    skill_name=str(datetime_skill.get("skill_name", "DateTime Skill")),
                    relative_path=str(datetime_skill.get("relative_path", "")),
                    module=str(datetime_skill.get("module", "")),
                    reason="Deterministic fallback selected DateTime skill.",
                )
            ],
            python_calls=[
                PythonCall(
                    order=1,
                    module=str(datetime_skill.get("module", "")),
                    function="get_datetime_string",
                    arguments={},
                )
            ],
            final_prompt_template="Return the datetime string directly to the user.",
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
) -> ExecutionPlan:
    skills_payload = load_skills_payload(skills_summary_path)
    planner_prompt = build_planner_prompt(
        user_prompt=user_prompt,
        planner_ask=planner_ask,
        skills_payload=skills_payload,
    )

    # Invoke LLM planner to propose skill calls in strict JSON shape.
    llm_text = call_ollama(model_name=model_name, prompt=planner_prompt, num_ctx=num_ctx)

    try:
        plan_dict = json.loads(extract_first_json_object(llm_text))
        return parse_execution_plan(plan_dict)
    except Exception:
        # Fall back deterministically so orchestration can proceed even with malformed planner output.
        return build_fallback_plan(user_prompt=user_prompt, skills_payload=skills_payload)
