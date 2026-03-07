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
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime
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
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from workspace_utils import get_logs_dir
from workspace_utils import get_schedules_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
USER_PROMPT              = "output the time"
REQUESTED_MODEL          = "20b"
DEFAULT_NUM_CTX          = 32768
MAX_ITERATIONS           = 3
MAX_CHAT_HISTORY_TURNS   = 10     # keep the last N user/assistant pairs; older turns are trimmed
SKILLS_SUMMARY_PATH      = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
SCHEDULES_DIR            = get_schedules_dir()
SCHEDULER_POLL_SECS      = 30
PLANNER_ASK              = (
    "Given the user prompt, select needed skills and return python_calls JSON. "
    "Choose the minimum required skills and provide explicit arguments for each python call."
)
LOG_DIR                  = get_logs_dir()


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
    parser.add_argument(
        "--analysetest",
        type=Path,
        default=None,
        metavar="CSV_FILE",
        help="Analyse a test results CSV produced by test_wrapper.py and exit.",
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        default=False,
        help="Start the scheduled-task runner using task_schedule.json.",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        default=False,
        help="Start the interactive dashboard (timeline + log + chat).",
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
        fallback = available_models[0]
        print(
            f"[model] '{requested_model}' not found — falling back to '{fallback}'.\n"
            f"        Available: {', '.join(available_models)}"
        )
        return fallback

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
        "Never claim a tool action succeeded unless the Python skill outputs explicitly show success.\n"
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
) -> tuple[str, int, int, bool, float]:
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

        # Slash commands bypass orchestration entirely.
        def _cli_clear_history():
            nonlocal conversation_history
            conversation_history = []

        def _cli_output(text: str, level: str = 'info') -> None:
            prefix = "[!] " if level == 'error' else ""
            print(f"{prefix}{text}")

        cli_ctx = SlashCommandContext(
            config        = config,
            output        = _cli_output,
            clear_history = _cli_clear_history,
        )
        if handle_slash(user_prompt, cli_ctx):
            continue

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
# MARK: DASHBOARD MODE
# ====================================================================================================
def run_dashboard_mode(
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Interactive dashboard: scheduler timeline + live log tail + chat, all in one terminal UI.

    Three background threads run concurrently:
      ollama-poll   refreshes the top bar with 'ollama ps' output every 10 s.
      log-tail      streams new lines from the latest run_*.txt log file every 2 s.
      scheduler     fires tasks from controldata/schedules/, one at a time, respecting llm_lock.

    Chat input dispatches orchestrate_prompt on a short-lived thread.  If the LLM is
    already busy with a scheduled task, the user gets an immediate 'LLM busy' message.
    """
    from scheduler import is_task_due, llm_lock, load_schedules_dir
    from ui.dashboard_app import DashboardApp
    from ui import colors as ui_colors
    from ollama_client import get_ollama_ps_rows

    shutdown = threading.Event()

    tasks         = load_schedules_dir(SCHEDULES_DIR)
    enabled_tasks = [t for t in tasks if t.get("enabled", True)]
    _startup      = datetime.now()
    last_run: dict[str, datetime | None] = {
        t["name"]: (_startup if t.get("schedule", {}).get("type") == "interval" else None)
        for t in enabled_tasks
    }

    chat_history: list[dict] = []

    def on_chat_submit(text: str) -> None:
        app.add_chat_line(f"You  \u25b6 {text}", ui_colors.INPUT)
        app.set_active_tab(DashboardApp.TAB_CHAT)

        # Slash commands bypass orchestration entirely.
        _level_colors = {
            'info':    ui_colors.BLUE,
            'item':    ui_colors.NORMAL,
            'error':   ui_colors.RED,
            'success': ui_colors.MAGENTA,
            'dim':     ui_colors.DIM,
        }

        def _dash_output(text: str, level: str = 'info') -> None:
            prefix = "Agent\u25b6 " if level in ('info', 'error', 'success') else "      "
            app.add_chat_line(f"{prefix}{text}", _level_colors.get(level, ui_colors.NORMAL))

        def _dash_clear_history() -> None:
            nonlocal chat_history
            chat_history = []

        dash_ctx = SlashCommandContext(
            config        = config,
            output        = _dash_output,
            clear_history = _dash_clear_history,
        )
        if handle_slash(text, dash_ctx):
            return

        def _run() -> None:
            nonlocal chat_history
            if not llm_lock.acquire(blocking=False):
                app.add_chat_line(
                    "Agent\u25b6 [LLM busy with a scheduled task \u2014 please wait]",
                    ui_colors.RED,
                )
                return
            try:
                run_log_path = create_log_file_path(log_dir=LOG_DIR)
                run_logger   = SessionLogger(run_log_path)
                run_logger.log_section_file_only("DASHBOARD CHAT")
                run_logger.log_file_only(f"User: {text}")

                hist = list(chat_history) if chat_history else None
                response, p_tokens, c_tokens, success, tps = orchestrate_prompt(
                    user_prompt=text,
                    config=config,
                    logger=run_logger,
                    conversation_history=hist,
                    quiet=True,
                )

                tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                run_logger.log_file_only(f"Agent: {response}")
                run_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
            finally:
                llm_lock.release()

            chat_history.append({"role": "user",      "content": text})
            chat_history.append({"role": "assistant", "content": response})
            if len(chat_history) > MAX_CHAT_HISTORY_TURNS * 2:
                chat_history = chat_history[-(MAX_CHAT_HISTORY_TURNS * 2):]

            app.add_chat_line(f"Agent\u25b6 {response}", ui_colors.NORMAL)
            app.add_chat_line(f"      [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)

        threading.Thread(target=_run, daemon=True, name="chat-dispatch").start()

    app = DashboardApp(
        tasks=enabled_tasks,
        last_run=last_run,
        on_submit=on_chat_submit,
        shutdown_event=shutdown,
        llm_lock=llm_lock,
    )

    # ---- Background: ollama ps ----
    def _ollama_poll() -> None:
        _COLS = ['name', 'size', 'processor', 'until']
        while not shutdown.is_set():
            try:
                rows = get_ollama_ps_rows()
                if rows:
                    w_name = max((len(r.get('name', '')) for r in rows), default=10)
                    header = f"{'NAME':<{w_name}}  SIZE        PROCESSOR   UNTIL"
                    lines  = [header]
                    for row in rows:
                        n = (row.get('name')      or '').ljust(w_name)
                        s = (row.get('size')      or '').ljust(10)
                        p = (row.get('processor') or '').ljust(10)
                        u =  row.get('until')     or ''
                        lines.append(f"{n}  {s}  {p}  {u}")
                    app.set_ollama_lines(lines)
                else:
                    app.set_ollama_lines(["  (no models currently loaded)"])
            except Exception as exc:
                app.set_ollama_lines([f"  ollama ps: {exc}"])
            for _ in range(20):    # 10 s in 0.5 s steps
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # ---- Background: log tail ----
    def _log_tail() -> None:
        watched: Path | None = None
        pos = 0
        while not shutdown.is_set():
            try:
                log_files = sorted(LOG_DIR.glob("run_*.txt"))
                if log_files:
                    latest = log_files[-1]
                    if latest != watched:
                        watched = latest
                        pos     = 0
                        app.add_log_line(f"\u2500\u2500\u2500 {latest.name} \u2500\u2500\u2500", ui_colors.BLUE)
                    size = latest.stat().st_size
                    if size > pos:
                        with latest.open(encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            new_text = fh.read()
                        pos = size
                        for line in new_text.splitlines():
                            app.add_log_line(line, ui_colors.DIM)
            except Exception:
                pass
            for _ in range(4):     # 2 s in 0.5 s steps
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # ---- Background: scheduler ----
    def _scheduler_loop() -> None:
        nonlocal enabled_tasks
        while not shutdown.is_set():
            # -- Reload schedule files and apply changes --
            try:
                fresh_tasks    = load_schedules_dir(SCHEDULES_DIR)
                fresh_enabled  = [t for t in fresh_tasks if t.get("enabled", True)]
                fresh_by_name  = {t["name"]: t for t in fresh_enabled}
                current_by_name = {t["name"]: t for t in enabled_tasks}

                added   = [n for n in fresh_by_name if n not in current_by_name]
                removed = [n for n in current_by_name if n not in fresh_by_name]
                changed = [
                    n for n in fresh_by_name
                    if n in current_by_name and fresh_by_name[n] != current_by_name[n]
                ]

                if added or removed or changed:
                    _reload_now = datetime.now()
                    for n in added:
                        stype = fresh_by_name[n].get("schedule", {}).get("type")
                        last_run[n] = _reload_now if stype == "interval" else None
                        app.add_log_line(f"[SCHED] New task loaded: {n}", ui_colors.MAGENTA)
                    for n in removed:
                        last_run.pop(n, None)
                        app.add_log_line(f"[SCHED] Task removed: {n}", ui_colors.DIM)
                    for n in changed:
                        last_run[n] = last_run.get(n)  # preserve last_run across edits
                        app.add_log_line(f"[SCHED] Task updated: {n}", ui_colors.DIM)
                    enabled_tasks = fresh_enabled
                    app.tasks = enabled_tasks
            except Exception as exc:
                app.add_log_line(f"[SCHED] Schedule reload error: {exc}", ui_colors.RED)

            now = datetime.now()
            for task in enabled_tasks:
                if shutdown.is_set():
                    break
                name    = task["name"]
                prompts = task.get("prompts", [])
                if not prompts:
                    continue
                if not is_task_due(task, last_run[name], now):
                    continue
                if llm_lock.locked():
                    app.add_log_line(f"[SCHED] '{name}' due but LLM busy \u2014 skipped", ui_colors.RED)
                    continue

                last_run[name] = now
                app.add_log_line(f"[SCHED] Starting: {name}", ui_colors.MAGENTA)
                app.add_chat_line(f"Sched\u25b6 Task started: {name}", ui_colors.MAGENTA)

                task_log_path = create_log_file_path(log_dir=LOG_DIR)
                task_logger   = SessionLogger(task_log_path)
                task_logger.log_section_file_only(f"SCHEDULER TASK (dashboard): {name}")

                with llm_lock:
                    conversation_history: list[dict] = []
                    for step_index, prompt_text in enumerate(prompts, start=1):
                        if shutdown.is_set():
                            break
                        app.add_log_line(f"  [Step {step_index}] {prompt_text[:70]}", ui_colors.DIM)
                        task_logger.log_file_only(f"[Step {step_index}] {prompt_text}")

                        response, p_tokens, c_tokens, success, tps = orchestrate_prompt(
                            user_prompt=prompt_text,
                            config=config,
                            logger=task_logger,
                            conversation_history=conversation_history if conversation_history else None,
                            quiet=True,
                        )
                        conversation_history.append({"role": "user",      "content": prompt_text})
                        conversation_history.append({"role": "assistant", "content": response})

                        tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
                        task_logger.log_file_only(f"[Step {step_index}] Agent: {response}")
                        task_logger.log_file_only(f"[{p_tokens:,} ctx{tps_str}]")
                        app.add_log_line(f"  \u2713 [{p_tokens:,} ctx{tps_str}]", ui_colors.DIM)
                        app.add_chat_line(
                            f"Sched\u25b6 [{name} step {step_index}] {response[:100]}",
                            ui_colors.BLUE,
                        )

                task_logger.log_file_only(f"[DASHBOARD] Task '{name}' completed.")
                app.add_log_line(f"[SCHED] Done: {name}", ui_colors.MAGENTA)

            for _ in range(SCHEDULER_POLL_SECS * 2):   # respects shutdown
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    # Register a SIGINT fallback in case the OS delivers it before kbhit sees it
    original_sigint = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame):  # noqa: ARG001
        shutdown.set()

    signal.signal(signal.SIGINT, _sigint_handler)

    threading.Thread(target=_ollama_poll,    daemon=True, name="dash-ollama").start()
    threading.Thread(target=_log_tail,       daemon=True, name="dash-log-tail").start()
    threading.Thread(target=_scheduler_loop, daemon=True, name="dash-scheduler").start()

    app.add_chat_line("  MiniAgentFramework Dashboard", ui_colors.TITLE)
    app.add_chat_line(f"  Model: {config.resolved_model}  |  Tab = Log\u2194Chat  |  Ctrl+C to stop",
                      ui_colors.DIM)
    app.add_log_line("  Log tail started \u2014 waiting for entries...", ui_colors.DIM)

    try:
        app.run()   # blocks; exits when Ctrl+C sets shutdown or _running=False
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        shutdown.set()
        logger.log("[DASHBOARD] Stopped cleanly.")


# ====================================================================================================
# MARK: SCHEDULER MODE
# ====================================================================================================
def run_scheduler_mode(
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Scheduled-task loop: fires prompt sequences according to task_schedule.json.

    Only one task runs at a time (single-LLM constraint enforced by llm_lock).
    If a task becomes due while another is in progress it is skipped for that poll cycle.

    Each task's prompt sequence shares a growing conversation_history so later prompts
    can reference the results of earlier ones within the same task run.

    Graceful shutdown: Ctrl+C (SIGINT) sets a shutdown flag and prints a notice.  The
    currently-running LLM call is allowed to finish; remaining steps in the active task
    are then skipped; the loop exits cleanly and restores the original signal handler.
    """
    from scheduler import is_task_due, llm_lock, load_schedules_dir

    shutdown        = threading.Event()
    original_sigint = signal.getsignal(signal.SIGINT)

    def _request_shutdown(signum, frame):  # noqa: ARG001
        print("\n[SCHEDULER] Shutdown requested — current LLM call will finish, then stopping.")
        shutdown.set()

    signal.signal(signal.SIGINT, _request_shutdown)

    tasks         = load_schedules_dir(SCHEDULES_DIR)
    enabled_tasks = [t for t in tasks if t.get("enabled", True)]
    _startup      = datetime.now()
    last_run: dict[str, datetime | None] = {
        t["name"]: (_startup if t.get("schedule", {}).get("type") == "interval" else None)
        for t in enabled_tasks
    }

    print(f"\nScheduler mode active — {len(enabled_tasks)} enabled task(s) | model: {config.resolved_model}")
    print(f"Log file: {log_path.as_posix()}")
    print(f"Poll interval: {SCHEDULER_POLL_SECS}s | Press Ctrl+C to stop after current task.\n")

    try:
        while not shutdown.is_set():
            # -- Reload schedule files and apply changes --
            try:
                fresh_tasks    = load_schedules_dir(SCHEDULES_DIR)
                fresh_enabled  = [t for t in fresh_tasks if t.get("enabled", True)]
                fresh_by_name  = {t["name"]: t for t in fresh_enabled}
                current_by_name = {t["name"]: t for t in enabled_tasks}

                added   = [n for n in fresh_by_name if n not in current_by_name]
                removed = [n for n in current_by_name if n not in fresh_by_name]
                changed = [
                    n for n in fresh_by_name
                    if n in current_by_name and fresh_by_name[n] != current_by_name[n]
                ]

                if added or removed or changed:
                    for n in added:
                        last_run[n] = None
                        print(f"[SCHEDULER] New task loaded: {n}")
                    for n in removed:
                        last_run.pop(n, None)
                        print(f"[SCHEDULER] Task removed: {n}")
                    for n in changed:
                        last_run[n] = last_run.get(n)
                        print(f"[SCHEDULER] Task updated: {n}")
                    enabled_tasks = fresh_enabled
                    print(f"[SCHEDULER] Schedule refreshed — {len(enabled_tasks)} enabled task(s)")
            except Exception as exc:
                print(f"[SCHEDULER] Schedule reload error: {exc}")

            now = datetime.now()

            for task in enabled_tasks:
                if shutdown.is_set():
                    break

                name    = task["name"]
                prompts = task.get("prompts", [])
                if not prompts:
                    continue

                if not is_task_due(task, last_run[name], now):
                    continue

                if llm_lock.locked():
                    logger.log(f"[SCHEDULER] Task '{name}' is due but LLM is busy — skipped this cycle")
                    continue

                last_run[name] = now
                logger.log_section(f"SCHEDULER TASK: {name}")
                print(f"[SCHEDULER] Starting task: {name} ({len(prompts)} prompt(s)) at {now.strftime('%H:%M:%S')}")

                with llm_lock:
                    conversation_history: list[dict] = []

                    for step_index, prompt_text in enumerate(prompts, start=1):
                        if shutdown.is_set():
                            print(f"  [SCHEDULER] Shutdown — skipping remaining steps for '{name}'.")
                            logger.log_file_only(f"[SCHEDULER] Task '{name}' step {step_index} skipped (shutdown).")
                            break

                        short = prompt_text[:70] + ("..." if len(prompt_text) > 70 else "")
                        print(f"  Step {step_index}/{len(prompts)}: {short}")
                        logger.log_file_only(f"[Step {step_index}] {prompt_text}")

                        response, p_tokens, c_tokens, success, tps = orchestrate_prompt(
                            user_prompt=prompt_text,
                            config=config,
                            logger=logger,
                            conversation_history=conversation_history if conversation_history else None,
                            quiet=True,
                        )

                        tps_str  = f" | {tps:.1f} tok/s" if tps > 0 else ""
                        preview  = response[:120] + ("..." if len(response) > 120 else "")
                        print(f"  [{p_tokens:,} ctx tokens{tps_str}] {preview}")
                        print()

                        # Thread this step's Q&A into history for the next prompt in the sequence.
                        conversation_history.append({"role": "user",      "content": prompt_text})
                        conversation_history.append({"role": "assistant", "content": response})

                print(f"[SCHEDULER] Task '{name}' completed.\n")
                logger.log(f"[SCHEDULER] Task '{name}' completed.")

            # Sleep in short increments so a shutdown request is noticed promptly.
            for _ in range(SCHEDULER_POLL_SECS * 2):  # 0.5s steps
                if shutdown.is_set():
                    break
                time.sleep(0.5)

    finally:
        signal.signal(signal.SIGINT, original_sigint)
        print("\nScheduler stopped.")
        logger.log("[SCHEDULER] Stopped cleanly.")


# ====================================================================================================
# MARK: MAIN ENTRYPOINT
# ====================================================================================================
def main() -> None:
    args = parse_main_args()

    # Analysis mode: parse a results CSV and exit without starting Ollama.
    if args.analysetest is not None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testcode"))
        from test_analyzer import run_analysis
        run_analysis(args.analysetest)
        return

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
    mode_label = "chat" if args.chat else "scheduler" if args.scheduler else "dashboard" if args.dashboard else "single-shot"
    logger.log(f"Mode:            {mode_label}")
    logger.log(f"num_ctx:         {args.num_ctx}")
    logger.log(f"Max iterations:  {MAX_ITERATIONS}")
    logger.log(format_running_model_report(resolved_model))
    logger.log(f"Log file:        {log_path.as_posix()}")

    if args.chat:
        run_chat_mode(config=config, logger=logger, log_path=log_path)
        return

    if args.scheduler:
        run_scheduler_mode(config=config, logger=logger, log_path=log_path)
        return

    if args.dashboard:
        run_dashboard_mode(config=config, logger=logger, log_path=log_path)
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
