# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Bridges the synchronous MiniAgentFramework skill pipeline to async MCP servers.
#
# Maintains a dedicated asyncio event loop in a background daemon thread.
# All async MCP operations are dispatched from the sync orchestration thread via
# asyncio.run_coroutine_threadsafe(...).result(), which blocks the calling thread
# until the result arrives - exactly like any other blocking I/O in the pipeline.
# No changes to orchestration, skill_executor, or any existing skill module are required
# beyond the two call sites that extend tool_defs and route tool calls.
#
# MCP servers are declared in default.json under "mcp_servers":
#   [{"name": "KoreDataGateway", "url": "http://localhost:8800/mcp"}]
#
# At start() the client connects to each server, calls list_tools(), and builds:
#   - _mcp_tool_defs:  OpenAI-format tool definitions merged into the LLM tool list
#   - _mcp_tool_index: tool_name -> {url, server} routing table for dispatch
#
# Related modules:
#   - skill_executor.py  -- calls is_mcp_tool() and call_mcp_tool() per invocation
#   - orchestration.py   -- calls get_mcp_tool_definitions() to extend tool_defs
#   - main.py            -- calls start() at application startup and stop() on exit
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import asyncio
import json
import threading

from pathlib import Path

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


# ====================================================================================================
# MARK: STATE
# ====================================================================================================
_loop:        asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None          = None

_mcp_tool_defs:      list[dict] = []
_mcp_tool_index:     dict[str, dict] = {}   # tool_name -> {"url": str, "server": str}
_configured_servers: list[dict] = []        # raw server entries from config, populated by start()

_CALL_TIMEOUT   = 30.0  # seconds applied to call_tool
_CONNECT_TIMEOUT = 5.0  # seconds to wait for list_tools during startup


# ====================================================================================================
# MARK: LIFECYCLE
# ====================================================================================================
def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


# ----------------------------------------------------------------------------------------------------
def start(config_path: Path) -> None:
    """Start the MCP event loop thread and enumerate tools from all configured servers.

    No-op when the mcp package is not installed or no servers are configured.
    """
    global _loop, _loop_thread, _mcp_tool_defs, _mcp_tool_index, _configured_servers

    if not _MCP_AVAILABLE:
        return

    servers             = _load_server_config(config_path)
    _configured_servers = servers
    if not servers:
        return

    _loop        = asyncio.new_event_loop()
    _loop_thread = threading.Thread(
        target = _run_loop,
        args   = (_loop,),
        daemon = True,
        name   = "mcp-event-loop",
    )
    _loop_thread.start()

    future          = asyncio.run_coroutine_threadsafe(_enumerate_all_servers(servers), _loop)
    try:
        defs, index = future.result(timeout=_CONNECT_TIMEOUT * len(servers) + 2)
    except TimeoutError:
        print(f"[mcp] Warning: tool enumeration timed out after {_CONNECT_TIMEOUT}s per server - continuing without MCP tools", flush=True)
        # Stop the event loop thread to avoid accumulating orphaned threads across restarts.
        _loop.call_soon_threadsafe(_loop.stop)
        if _loop_thread is not None:
            _loop_thread.join(timeout=2.0)
        _loop        = None
        _loop_thread = None
        defs, index  = [], {}
    _mcp_tool_defs  = defs
    _mcp_tool_index = index

    count       = len(defs)
    server_list = ", ".join(s.get("name") or s["url"] for s in servers)
    print(f"[mcp] {count} tool(s) registered from: {server_list}", flush=True)


# ----------------------------------------------------------------------------------------------------
def stop() -> None:
    """Stop the MCP event loop thread. Called on application shutdown."""
    global _loop, _loop_thread

    if _loop is not None:
        _loop.call_soon_threadsafe(_loop.stop)
        _loop        = None
        _loop_thread = None


# ----------------------------------------------------------------------------------------------------
def reconnect() -> tuple[int, list[str]]:
    """Re-enumerate tools from all configured servers without restarting MAF.

    Starts the event loop thread if it was never started or died after a timeout.
    Returns (total_tool_count, [status_line, ...]) so the caller can report results.
    """
    global _loop, _loop_thread, _mcp_tool_defs, _mcp_tool_index

    if not _MCP_AVAILABLE:
        return 0, ["mcp package not installed"]

    servers = _configured_servers
    if not servers:
        return 0, ["No servers configured in default.json"]

    if _loop is None or _loop_thread is None or not _loop_thread.is_alive():
        _loop        = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target = _run_loop,
            args   = (_loop,),
            daemon = True,
            name   = "mcp-event-loop",
        )
        _loop_thread.start()

    future = asyncio.run_coroutine_threadsafe(_enumerate_all_servers(servers), _loop)
    try:
        defs, index = future.result(timeout=_CONNECT_TIMEOUT * len(servers) + 2)
    except TimeoutError:
        return 0, [f"Reconnect timed out after {_CONNECT_TIMEOUT:.0f}s per server"]

    _mcp_tool_defs  = defs
    _mcp_tool_index = index

    registered_urls: dict[str, int] = {}
    for info in index.values():
        registered_urls[info["url"]] = registered_urls.get(info["url"], 0) + 1

    lines = []
    for srv in servers:
        name  = srv.get("name") or srv.get("url", "?")
        url   = srv.get("url", "?")
        count = registered_urls.get(url, 0)
        ok    = count > 0
        lines.append(f"  {'OK  ' if ok else 'FAIL'}  {name}  {url}  ({count} tool(s))")

    return len(defs), lines


# ====================================================================================================
# MARK: PUBLIC API
# ====================================================================================================
def is_mcp_tool(tool_name: str) -> bool:
    return tool_name in _mcp_tool_index


# ----------------------------------------------------------------------------------------------------
def get_mcp_tool_definitions() -> list[dict]:
    return list(_mcp_tool_defs)


# ----------------------------------------------------------------------------------------------------
def get_server_status() -> list[dict]:
    """Return [{name, url, tool_count, ok}] for each configured server."""
    registered_urls: dict[str, int] = {}
    for info in _mcp_tool_index.values():
        registered_urls[info["url"]] = registered_urls.get(info["url"], 0) + 1
    return [
        {
            "name":       srv.get("name") or srv.get("url", "?"),
            "url":        srv.get("url", "?"),
            "tool_count": registered_urls.get(srv.get("url", ""), 0),
            "ok":         registered_urls.get(srv.get("url", ""), 0) > 0,
        }
        for srv in _configured_servers
    ]


# ----------------------------------------------------------------------------------------------------
def call_mcp_tool(tool_name: str, arguments: dict) -> object:
    """Call an MCP tool synchronously from the orchestration thread.

    Blocks until the remote call completes or _CALL_TIMEOUT seconds elapses.
    Returns a string for text results, a list of dicts for mixed content,
    or an "Error: ..." string when the server signals isError.
    """
    if _loop is None:
        raise RuntimeError("MCP client is not running - call mcp_client.start() at startup")

    entry = _mcp_tool_index.get(tool_name)
    if entry is None:
        raise RuntimeError(f"MCP tool '{tool_name}' is not registered")

    future = asyncio.run_coroutine_threadsafe(
        _call_tool_async(entry["url"], tool_name, arguments),
        _loop,
    )
    return future.result(timeout=_CALL_TIMEOUT)


# ====================================================================================================
# MARK: INTERNAL - CONFIG
# ====================================================================================================
def _load_server_config(config_path: Path) -> list[dict]:
    try:
        data    = json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("mcp_servers", [])
        return [s for s in servers if isinstance(s, dict) and s.get("url")]
    except FileNotFoundError:
        return []
    except Exception as exc:
        import sys
        print(f"[mcp_client] Warning: could not load MCP server config from {config_path}: {exc}", file=sys.stderr)
        return []


# ====================================================================================================
# MARK: INTERNAL - ASYNC OPERATIONS
# ====================================================================================================
async def _enumerate_all_servers(servers: list[dict]) -> tuple[list[dict], dict]:
    defs:  list[dict] = []
    index: dict       = {}

    for server in servers:
        name = server.get("name") or server["url"]
        url  = server["url"]
        try:
            server_defs, server_index = await asyncio.wait_for(
                _list_tools_async(url, name), timeout=_CONNECT_TIMEOUT
            )
            defs.extend(server_defs)
            index.update(server_index)
        except Exception as exc:
            print(f"[mcp] Warning: could not connect to '{name}' at {url}: {exc}", flush=True)

    return defs, index


# ----------------------------------------------------------------------------------------------------
async def _list_tools_async(url: str, server_name: str) -> tuple[list[dict], dict]:
    defs:  list[dict] = []
    index: dict       = {}

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

            for tool in result.tools:
                schema   = tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
                tool_def = {
                    "type": "function",
                    "function": {
                        "name":        tool.name,
                        "description": tool.description or "",
                        "parameters":  schema,
                    },
                }
                defs.append(tool_def)
                index[tool.name] = {"url": url, "server": server_name}

    return defs, index


# ----------------------------------------------------------------------------------------------------
async def _call_tool_async(url: str, tool_name: str, arguments: dict) -> object:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if result.isError:
        text_parts = [c.text for c in result.content if hasattr(c, "text") and c.text]
        error_msg  = " ".join(text_parts) if text_parts else "MCP tool returned an error"
        return f"Error: {error_msg}"

    text_parts = [c.text for c in result.content if hasattr(c, "text") and c.text]
    if text_parts:
        return "\n".join(text_parts) if len(text_parts) > 1 else text_parts[0]

    return [c.__dict__ for c in result.content]
