from pathlib import Path

from KoreAgent.orchestration import ConversationHistory
from KoreAgent.orchestration import SessionContext
from KoreAgent.orchestration import orchestrate_prompt


def make_task_session(
    session_id: str,
    persist_path: Path | None,
    max_turns: int = 10,
) -> tuple[ConversationHistory, SessionContext]:
    history = ConversationHistory(max_turns=max_turns)
    ctx = SessionContext(session_id=session_id, persist_path=persist_path)
    return history, ctx


def run_prompt_batch(
    prompts: list,
    *,
    session_id: str,
    persist_path: Path,
    config,
    logger,
    quiet: bool = True,
    max_turns: int = 10,
) -> list[dict]:
    history, session_ctx = make_task_session(
        session_id=session_id,
        persist_path=persist_path,
        max_turns=max_turns,
    )
    results: list[dict] = []

    for prompt_text in prompts:
        current = prompt_text.get("prompt", "") if isinstance(prompt_text, dict) else str(prompt_text)
        if not current:
            continue
        response, p_tokens, _c, ok, tps = orchestrate_prompt(
            user_prompt=current,
            config=config,
            logger=logger,
            conversation_history=history.as_list() or None,
            session_context=session_ctx,
            quiet=quiet,
        )
        history.add(current, response)
        results.append({
            "prompt": current,
            "response": response,
            "prompt_tokens": p_tokens,
            "ok": ok,
            "tps": tps,
        })

    return results
