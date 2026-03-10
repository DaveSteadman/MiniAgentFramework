# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# CLI entrypoint for the MiniAgentFramework.  Dispatches to one of four execution modes:
#
#   single-shot  Orchestrate one prompt and exit (default).
#   chat         Interactive multi-turn REPL; verbose detail goes to log file only.
#   scheduler    Fire tasks from controldata/schedules/ on their schedules.
#   dashboard    Interactive TUI: timeline + log tail + chat panel.
#
# Core orchestration pipeline lives in orchestration.py.
# Dashboard mode lives in modes/dashboard.py.
#
# Related modules:
#   - orchestration.py     -- OrchestratorConfig, ConversationHistory, orchestrate_prompt, ...
#   - modes/dashboard.py   -- run_dashboard_mode
#   - ollama_client.py     -- Ollama server management and LLM calls
#   - planner_engine.py    -- structured plan construction and skills catalog loading
#   - scheduler.py         -- load_schedules_dir, is_task_due, llm_lock
#   - runtime_logger.py    -- SessionLogger, create_log_file_path
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import argparse
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

from modes.dashboard import run_dashboard_mode
from ollama_client import ensure_ollama_running
from ollama_client import format_running_model_report
from ollama_client import get_llm_timeout
from orchestration import ConversationHistory
from orchestration import OrchestratorConfig
from orchestration import orchestrate_prompt
from orchestration import resolve_execution_model
from planner_engine import load_skills_payload
from runtime_logger import create_log_file_path
from runtime_logger import SessionLogger
from scheduler import initial_last_run, is_task_due
from scheduler import llm_lock
from scheduler import load_schedules_dir
from slash_commands import SlashCommandContext
from slash_commands import handle as handle_slash
from workspace_utils import get_logs_dir
from workspace_utils import get_schedules_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
USER_PROMPT              = "output the time"
REQUESTED_MODEL          = "20b"
DEFAULT_NUM_CTX          = 131072
MAX_ITERATIONS           = 3
MAX_CHAT_HISTORY_TURNS   = 10     # keep the last N user/assistant pairs; older turns are trimmed
SKILLS_SUMMARY_PATH      = Path(__file__).resolve().parent / "skills" / "skills_summary.md"
SCHEDULES_DIR            = get_schedules_dir()
SCHEDULER_POLL_SECS      = 30
LOG_DIR                  = get_logs_dir()


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
    parser.add_argument(
        "--scheduled-item",
        type=str,
        default=None,
        metavar="NAME",
        help="Run a single named scheduled task immediately (debugging aid; ignores enabled flag).",
    )
    return parser.parse_args()


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
    history = ConversationHistory(max_turns=MAX_CHAT_HISTORY_TURNS)
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
            history.clear()

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
            conversation_history=history.as_list() or None,
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

        history.add(user_prompt, final_response)


# run_dashboard_mode lives in modes/dashboard.py and is imported at the top of this file.


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
        t["name"]: initial_last_run(t, _startup)
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
                        last_run[n] = initial_last_run(fresh_by_name[n], datetime.now())
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

                if not llm_lock.acquire(blocking=False):
                    logger.log(f"[SCHEDULER] Task '{name}' is due but LLM is busy — will retry next cycle")
                    continue

                # Lock is now held — record start time and run the task.
                last_run[name] = now
                logger.log_section(f"SCHEDULER TASK: {name}")
                print(f"[SCHEDULER] Starting task: {name} ({len(prompts)} prompt(s)) at {now.strftime('%H:%M:%S')}")

                try:
                    task_hist  = ConversationHistory()
                    sched_ctx  = SlashCommandContext(
                        config        = config,
                        output        = lambda text, level='info': logger.log_file_only(f"[slash/{level}] {text}"),
                        clear_history = task_hist.clear,
                    )

                    for step_index, prompt_text in enumerate(prompts, start=1):
                        if shutdown.is_set():
                            print(f"  [SCHEDULER] Shutdown — skipping remaining steps for '{name}'.")
                            logger.log_file_only(f"[SCHEDULER] Task '{name}' step {step_index} skipped (shutdown).")
                            break

                        short = prompt_text[:70] + ("..." if len(prompt_text) > 70 else "")
                        print(f"  Step {step_index}/{len(prompts)}: {short}")
                        logger.log_file_only(f"[Step {step_index}] {prompt_text}")

                        if handle_slash(prompt_text, sched_ctx):
                            print(f"  [slash command handled]")
                            continue

                        response, p_tokens, _c, success, tps = orchestrate_prompt(
                            user_prompt=prompt_text,
                            config=config,
                            logger=logger,
                            conversation_history=task_hist.as_list() or None,
                            quiet=True,
                        )

                        tps_str  = f" | {tps:.1f} tok/s" if tps > 0 else ""
                        preview  = response[:120] + ("..." if len(response) > 120 else "")
                        print(f"  [{p_tokens:,} ctx tokens{tps_str}] {preview}")
                        print()

                        task_hist.add(prompt_text, response)

                    print(f"[SCHEDULER] Task '{name}' completed.\n")
                    logger.log(f"[SCHEDULER] Task '{name}' completed.")
                finally:
                    llm_lock.release()

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
# MARK: SCHEDULE ITEM MODE  (debugging aid)
# ====================================================================================================
def run_schedule_item_mode(
    item_name: str,
    config: OrchestratorConfig,
    logger: SessionLogger,
    log_path: Path,
) -> None:
    """Run a single named task from the schedules directory immediately.

    Loads all schedule files, finds the first task whose 'name' matches item_name
    (case-sensitive), and runs its prompt sequence in order.  The enabled flag is
    intentionally ignored so disabled tasks can be exercised for debugging.
    """
    tasks = load_schedules_dir(SCHEDULES_DIR)
    task  = next((t for t in tasks if t.get("name") == item_name), None)

    if task is None:
        available = ", ".join(t.get("name", "?") for t in tasks) or "(none)"
        print(f"[scheduled-item] No task named '{item_name}' found in {SCHEDULES_DIR}")
        print(f"[scheduled-item] Available tasks: {available}")
        return

    prompts = task.get("prompts", [])
    if not prompts:
        print(f"[scheduled-item] Task '{item_name}' has no prompts — nothing to run.")
        return

    print(f"\nScheduled-item mode — running task: '{item_name}' ({len(prompts)} prompt(s))")
    print(f"Log file: {log_path.as_posix()}\n")
    logger.log_section(f"SCHEDULE ITEM: {item_name}")

    task_hist = ConversationHistory()
    sched_ctx = SlashCommandContext(
        config        = config,
        output        = lambda text, level='info': logger.log_file_only(f"[slash/{level}] {text}"),
        clear_history = task_hist.clear,
    )

    for step_index, prompt_text in enumerate(prompts, start=1):
        short = prompt_text[:70] + ("..." if len(prompt_text) > 70 else "")
        print(f"  Step {step_index}/{len(prompts)}: {short}")
        logger.log_file_only(f"[Step {step_index}] {prompt_text}")

        if handle_slash(prompt_text, sched_ctx):
            print(f"  [slash command handled]")
            continue

        response, p_tokens, _c, success, tps = orchestrate_prompt(
            user_prompt=prompt_text,
            config=config,
            logger=logger,
            conversation_history=task_hist.as_list() or None,
            quiet=True,
        )

        tps_str = f" | {tps:.1f} tok/s" if tps > 0 else ""
        preview = response[:120] + ("..." if len(response) > 120 else "")
        print(f"  [{p_tokens:,} ctx tokens{tps_str}] {preview}")
        print()

        task_hist.add(prompt_text, response)

    print(f"Task '{item_name}' completed.")
    logger.log(f"[SCHEDULE ITEM] Task '{item_name}' completed.")


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
    mode_label = (
        "chat"          if args.chat          else
        "scheduler"     if args.scheduler     else
        "dashboard"     if args.dashboard     else
        f"scheduled-item:{args.scheduled_item}" if args.scheduled_item else
        "single-shot"
    )
    logger.log(f"Mode:            {mode_label}")
    logger.log(f"num_ctx:         {args.num_ctx}")
    logger.log(f"LLM timeout:     {get_llm_timeout()}s")
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

    if args.scheduled_item:
        run_schedule_item_mode(item_name=args.scheduled_item, config=config, logger=logger, log_path=log_path)
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
