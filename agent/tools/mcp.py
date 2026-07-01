"""
MCP (Model Context Protocol) — config-driven, auto-connected tool servers.

Configuration lives in .mcp.json (project root).  On startup, init_mcp()
reads the file and connects to every listed server automatically — no
manual connect_mcp calls needed.

Servers are connected via stdio subprocess or HTTP.  Each connection runs
its own asyncio event loop in a background daemon thread.

Format (.mcp.json):
{
  "mcpServers": {
    "<name>": {
      "command": "...",        // stdio: executable
      "args": [...],           // stdio: arguments
      "env": {...}             // optional env vars
    },
    "<name>": {
      "url": "http://..."      // HTTP / SSE
    }
  }
}
"""

import asyncio, concurrent.futures, json, threading
from pathlib import Path

from agent.config import WORKDIR, mcp_clients, _DISALLOWED_CHARS


def normalize_mcp_name(name: str) -> str:
    """Replace non [a-zA-Z0-9_-] with underscore."""
    return _DISALLOWED_CHARS.sub('_', name)


# ═════════════════════════════════════════════════════════════════════════════
# Real MCP client (stdio / HTTP)
# ═════════════════════════════════════════════════════════════════════════════

class RealMCPClient:
    """Connects to a real MCP server via stdio subprocess or HTTP.

    An asyncio event loop runs in a daemon thread; tool calls from the
    main (sync) thread are dispatched via run_coroutine_threadsafe.
    """

    def __init__(self, name: str, *,
                 command: str | None = None,
                 args: list[str] | None = None,
                 url: str | None = None,
                 env: dict[str, str] | None = None,
                 timeout: float = 30.0):
        self.name = name
        self.tools: list[dict] = []
        self._command = command
        self._args = args or []
        self._url = url
        self._env = env
        self._timeout = timeout

        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._transport = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    # ── public ──────────────────────────────────────────────────────────

    def connect(self) -> str:
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._start_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=15):
            return f"MCP '{self.name}': connection timed out (15s)"
        if self._error:
            return f"MCP '{self.name}': {self._error}"
        names = [t["name"] for t in self.tools]
        return f"Connected '{self.name}' ({len(self.tools)} tools: {', '.join(names)})"

    def call_tool(self, tool_name: str, args: dict) -> str:
        if not self._loop or not self._session:
            return f"MCP error: '{self.name}' not connected"
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(tool_name, args), self._loop
        )
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            return f"MCP error: tool '{tool_name}' timed out after {self._timeout}s"
        except Exception as e:
            return f"MCP error: {e}"

    def disconnect(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._disconnect_async(), self._loop)

    # ── async internals ─────────────────────────────────────────────────

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_discover())
        except Exception as e:
            self._error = str(e)
        finally:
            self._ready.set()
            if not self._error:
                self._loop.run_forever()

    async def _connect_and_discover(self):
        from mcp import ClientSession

        if self._url:
            from mcp.client.streamable_http import streamable_http_client
            transport = streamable_http_client(self._url)
        elif self._command:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            transport = stdio_client(StdioServerParameters(
                command=self._command, args=self._args, env=self._env,
            ))
        else:
            raise ValueError("Either 'command' (stdio) or 'url' (HTTP) is required")

        self._transport = transport
        result = await transport.__aenter__()
        read, write = result[0], result[1]
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._session = session

        result = await session.list_tools()
        self.tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": getattr(t, 'inputSchema',
                              getattr(t, 'input_schema', {})),
            }
            for t in result.tools
        ]

    async def _call_tool_async(self, tool_name: str, args: dict) -> str:
        from mcp import types as mcp_types
        result = await self._session.call_tool(tool_name, arguments=args)
        parts = []
        for content in result.content:
            if isinstance(content, mcp_types.TextContent):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts) if parts else "(empty result)"

    async def _disconnect_async(self):
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
            if self._transport:
                await self._transport.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            if self._loop:
                self._loop.stop()


# ═════════════════════════════════════════════════════════════════════════════
# init_mcp — auto-connect to all servers in .mcp.json
# ═════════════════════════════════════════════════════════════════════════════

MCP_CONFIG_PATH = WORKDIR / ".mcp.json"


def _load_mcp_config() -> dict[str, dict]:
    if not MCP_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(MCP_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("mcpServers", {})


def init_mcp() -> list[str]:
    """Read .mcp.json, connect to every listed server.  Called once at startup.

    Returns a list of status messages (for logging).
    """
    servers = _load_mcp_config()
    if not servers:
        print("  \033[90m[mcp] no .mcp.json found or empty, skipping\033[0m")
        return []

    lines: list[str] = []
    for name, cfg in servers.items():
        if name in mcp_clients:
            lines.append(f"'{name}': already connected, skipped")
            continue

        command = cfg.get("command")
        args = cfg.get("args")
        url = cfg.get("url")
        env = cfg.get("env")

        if not command and not url:
            lines.append(f"'{name}': missing 'command' or 'url', skipped")
            continue

        client = RealMCPClient(
            name, command=command, args=args, url=url, env=env,
        )
        result = client.connect()
        if "timed out" in result or result.startswith("MCP '"):
            lines.append(f"'{name}': FAILED — {result}")
            print(f"  \033[31m[mcp] {name}: FAILED — {result}\033[0m")
        else:
            mcp_clients[name] = client
            lines.append(f"'{name}': {result}")
            print(f"  \033[31m[mcp] {name}: {result}\033[0m")
    return lines


# ═════════════════════════════════════════════════════════════════════════════
# connect_mcp — runtime tool for adding servers after startup
# ═════════════════════════════════════════════════════════════════════════════

def connect_mcp(name: str, *,
                command: str | None = None,
                args: list[str] | None = None,
                url: str | None = None,
                env: dict[str, str] | None = None) -> str:
    """Connect to an MCP server at runtime.

    Either *command* (stdio) or *url* (HTTP) is required.
    The server's tools become available as mcp__<server>__<tool>.
    """
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"

    if not command and not url:
        return (
            f"Error: specify 'command'+'args' (stdio) or 'url' (HTTP). "
            f"Pre-configured servers in .mcp.json are auto-connected at startup."
        )

    client = RealMCPClient(
        name, command=command, args=args, url=url, env=env,
    )
    result = client.connect()
    if "timed out" in result or result.startswith("MCP '"):
        return result
    mcp_clients[name] = client
    return result
