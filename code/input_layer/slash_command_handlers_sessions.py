import json
import re
import time
from typing import Callable

from input_layer.slash_command_context import SlashCommandContext
from utils.workspace_utils import get_chatsessions_day_dir
from utils.workspace_utils import get_chatsessions_dir
from utils.workspace_utils import get_chatsessions_named_dir


def _readable_session_path(session_id: str):
    named_path = get_chatsessions_named_dir() / f"{session_id}.json"
    if named_path.exists():
        return named_path

    day_path = get_chatsessions_day_dir() / f"{session_id}.json"
    if day_path.exists():
        return day_path

    root_path = get_chatsessions_dir() / f"{session_id}.json"
    if root_path.exists():
        return root_path

    dated_matches = sorted(get_chatsessions_dir().glob(f"*/{session_id}.json"), reverse=True)
    if dated_matches:
        return dated_matches[0]

    return day_path


def _session_file_scan() -> list[tuple]:
    named_dir = get_chatsessions_named_dir()
    results = []
    if not named_dir.exists():
        return results
    for path in sorted(named_dir.glob("*.json")):
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append((path, data))
            except Exception:
                pass
    return results


def _session_set_name(session_id: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise ValueError(f"Name '{name}' produces an empty slug - use letters or digits.")

    new_session_id = f"session_{slug}"
    named_dir = get_chatsessions_named_dir()
    target_path = named_dir / f"{new_session_id}.json"
    current_named = named_dir / f"{session_id}.json"
    current_day = get_chatsessions_day_dir() / f"{session_id}.json"
    legacy_root = get_chatsessions_dir() / f"{session_id}.json"
    src_path = (
        current_named if current_named.exists() else
        (current_day if current_day.exists() else (legacy_root if legacy_root.exists() else None))
    )

    if src_path is None:
        resolved = _readable_session_path(session_id)
        src_path = resolved if resolved.exists() else None

    if target_path.exists() and src_path != target_path:
        raise ValueError(f"A session named '{name}' already exists. Choose a different name.")

    data = {}
    if src_path:
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data["name"] = name
    named_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if src_path and src_path != target_path and src_path.parent != named_dir:
        try:
            src_path.unlink()
        except Exception:
            pass
    return new_session_id


def _cmd_session(arg: str, ctx: SlashCommandContext) -> None:
    sub_parts = arg.strip().split(None, 1)
    sub = sub_parts[0].lower() if sub_parts else ""
    rest = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if sub == "name":
        if not rest:
            ctx.output("Usage: /session name <alias>", "dim")
            return
        if not ctx.session_id:
            ctx.output("Session naming is not available in this mode.", "error")
            return
        try:
            new_session_id = _session_set_name(ctx.session_id, rest)
        except ValueError as exc:
            ctx.output(str(exc), "error")
            return
        ctx.output(f"Session named '{rest}'.", "success")
        ctx.output(f"  File: named/session_{new_session_id.removeprefix('session_')}.json", "dim")
        if ctx.rename_session:
            ctx.rename_session(new_session_id, rest)
        return

    if sub == "list":
        sessions = _session_file_scan()
        named = [(path, data) for path, data in sessions if data.get("name")]
        if not named:
            ctx.output("No named sessions found. Use /session name <alias> to name the current session.", "dim")
            return
        ctx.output(f"{len(named)} named session(s):", "info")
        for path, data in named:
            name = data["name"]
            turns = len(data.get("turns", []))
            summaries = len(data.get("summaries", []))
            detail = f"{turns} turn(s)"
            if summaries:
                detail += f" + {summaries} compacted"
            ctx.output(f"  {name:<30}  {detail:<28}  [{path.stem}]", "item")
        return

    if sub == "resume":
        if not rest:
            ctx.output("Usage: /session resume <name>", "dim")
            return
        if not ctx.switch_session:
            ctx.output("Session switching is not available in this mode.", "error")
            return
        sessions = _session_file_scan()
        match = next(((path, data) for path, data in sessions if data.get("name", "").lower() == rest.lower()), None)
        if not match:
            ctx.output(f"No session named '{rest}' found. Use /session list to see available sessions.", "error")
            return
        path, data = match
        session_id = path.stem
        turns = len(data.get("turns", []))
        summaries = len(data.get("summaries", []))
        ctx.output(f"Switching to '{rest}' - {turns} turn(s), {summaries} compacted.", "success")
        ctx.switch_session(session_id, rest)
        return

    if sub == "resumecopy":
        parts2 = rest.split(None, 1)
        if len(parts2) < 2:
            ctx.output("Usage: /session resumecopy <oldname> <newname>", "dim")
            return
        src_name, dst_name = parts2[0].strip(), parts2[1].strip()
        if not ctx.switch_session:
            ctx.output("Session switching is not available in this mode.", "error")
            return
        sessions = _session_file_scan()
        match = next(((path, data) for path, data in sessions if data.get("name", "").lower() == src_name.lower()), None)
        if not match:
            match = next(((path, data) for path, data in sessions if src_name.lower() in data.get("name", "").lower()), None)
        if not match:
            ctx.output(f"No session named '{src_name}' found. Use /session list to see available sessions.", "error")
            return
        src_path, src_data = match
        slug = re.sub(r"[^a-z0-9]+", "_", dst_name.lower()).strip("_")
        if not slug:
            ctx.output(f"Name '{dst_name}' produces an empty slug - use letters or digits.", "error")
            return
        new_session_id = f"session_{slug}"
        named_dir = get_chatsessions_named_dir()
        target_path = named_dir / f"{new_session_id}.json"
        if target_path.exists():
            ctx.output(f"A session named '{dst_name}' already exists. Choose a different name.", "error")
            return
        copy_data = dict(src_data)
        copy_data["name"] = dst_name
        named_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(copy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        turns = len(copy_data.get("turns", []))
        summaries = len(copy_data.get("summaries", []))
        ctx.output(f"Copied '{src_data.get('name', src_path.stem)}' -> '{dst_name}' ({turns} turn(s), {summaries} compacted).", "success")
        ctx.output(f"  File: named/{new_session_id}.json", "dim")
        ctx.switch_session(new_session_id, dst_name)
        return

    if sub == "park":
        if not ctx.switch_session:
            ctx.output("Session parking is not available in this mode.", "error")
            return
        new_id = f"web_{int(time.time() * 1000)}"
        ctx.output("Current session parked - starting fresh chat.", "success")
        ctx.switch_session(new_id, "")
        return

    if sub == "delete":
        if not rest:
            ctx.output("Usage: /session delete <name>  |  /session delete all", "dim")
            return
        sessions = _session_file_scan()
        if rest.lower() == "all":
            if not sessions:
                ctx.output("No named sessions to delete.", "dim")
                return
            deleted_current = False
            count = 0
            for path, data in sessions:
                try:
                    if path.stem == ctx.session_id:
                        deleted_current = True
                    path.unlink()
                    count += 1
                    ctx.output(f"  Deleted '{data.get('name', path.stem)}'.", "item")
                except Exception as exc:
                    ctx.output(f"  Error deleting '{path.name}': {exc}", "error")
            ctx.output(f"{count} session(s) deleted.", "success")
            if deleted_current and ctx.switch_session:
                ctx.output("Current session was deleted - starting fresh chat.", "info")
                ctx.switch_session(f"web_{int(time.time() * 1000)}", "")
            return
        matches = [(path, data) for path, data in sessions if data.get("name", "").lower() == rest.lower()]
        if not matches:
            ctx.output(f"No session with exact name '{rest}' found. Use /session list to check names.", "error")
            return
        deleted_current = False
        for path, data in matches:
            try:
                if path.stem == ctx.session_id:
                    deleted_current = True
                path.unlink()
                ctx.output(f"Deleted session '{data.get('name', path.stem)}'.", "success")
            except Exception as exc:
                ctx.output(f"Error deleting '{path.name}': {exc}", "error")
        if deleted_current and ctx.switch_session:
            ctx.output("Current session was deleted - starting fresh chat.", "info")
            ctx.switch_session(f"web_{int(time.time() * 1000)}", "")
        return

    if sub == "info":
        if not ctx.session_id:
            ctx.output("No active session.", "dim")
            return
        path = _readable_session_path(ctx.session_id)
        if not path.exists():
            ctx.output(f"Session '{ctx.session_id}' has no saved file yet.", "dim")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            ctx.output("Could not read session file.", "error")
            return
        ctx.output("Current session:", "info")
        ctx.output(f"  Name:       {data.get('name', '(unnamed)')}", "item")
        ctx.output(f"  ID:         {ctx.session_id}", "item")
        ctx.output(f"  Turns:      {len(data.get('turns', []))}", "item")
        ctx.output(f"  Summaries:  {len(data.get('summaries', []))}", "item")
        ctx.output(f"  File:       {path}", "item")
        return

    ctx.output("Usage: /session <name|list|resume|resumecopy|park|delete|info>", "dim")
    ctx.output("  /session name <alias>                - name the current session", "item")
    ctx.output("  /session list                        - list all named sessions", "item")
    ctx.output("  /session resume <name>               - switch to a named session", "item")
    ctx.output("  /session resumecopy <old> <new>      - copy a session to a new name and resume it", "item")
    ctx.output("  /session park                        - save current session and start a fresh one", "item")
    ctx.output("  /session delete <name>               - delete a named session (substring match)", "item")
    ctx.output("  /session delete all                  - delete all named sessions", "item")
    ctx.output("  /session info                        - show current session details", "item")


def register_session_slash_commands(registry: dict[str, Callable], descriptions: dict[str, str]) -> None:
    registry["/session"] = _cmd_session
    descriptions["/session"] = "name <alias> | list | resume <name> | park | delete <name|all> | info  - manage named session contexts"
