"""
MCP (Model Context Protocol) — real + mock tool servers.

Real servers are connected via stdio subprocess or HTTP.  Each connection
runs its own asyncio event loop in a background thread.  Discovered tools
are merged into the normal tool pool with mcp__<server>__<tool> naming.

Mock servers (docs, deploy) remain available for teaching / offline use.
"""

import asyncio, concurrent.futures, threading
from typing import Callable

from agent.config import mcp_clients, _DISALLOWED_CHARS


def normalize_mcp_name(name: str) -> str:
    """Replace non [a-zA-Z0-9_-] with underscore."""
    return _DISALLOWED_CHARS.sub('_', name)


# ═════════════════════════════════════════════════════════════════════════════
# Base
# ═════════════════════════════════════════════════════════════════════════════

class MCPClient:
    """Base: holds tool definitions and a call_tool(name, args) → str interface."""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, Callable] = {}

    def register(self, tool_defs: list[dict], handlers: dict[str, Callable]):
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as e:
            return f"MCP error: {e}"

    def disconnect(self):
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Real MCP client (stdio / HTTP)
# ═════════════════════════════════════════════════════════════════════════════

class RealMCPClient(MCPClient):
    """Connects to a real MCP server via stdio subprocess or HTTP.

    An asyncio event loop runs in a daemon thread; tool calls from the
    main (sync) thread are dispatched to it via run_coroutine_threadsafe.
    """

    def __init__(self, name: str, *,
                 command: str | None = None,
                 args: list[str] | None = None,
                 url: str | None = None,
                 env: dict[str, str] | None = None,
                 timeout: float = 30.0):
        super().__init__(name)
        self._command = command
        self._args = args or []
        self._url = url
        self._env = env
        self._timeout = timeout

        # Async internals — set by _start_loop
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._transport = None  # (read, write) context manager
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    # ── public ──────────────────────────────────────────────────────────

    def connect(self) -> str:
        """Start the event-loop thread, initialise the MCP session, discover tools.

        Returns a success/error message (suitable for the connect_mcp tool).
        """
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._start_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=15):
            return f"MCP '{self.name}': connection timed out (15 s)"
        if self._error:
            return f"MCP '{self.name}': {self._error}"
        tool_names = [t["name"] for t in self.tools]
        print(f"  \033[31m[mcp] connected: {self.name} → {tool_names}\033[0m")
        return (
            f"Connected to MCP server '{self.name}'. "
            f"Discovered {len(self.tools)} tools: {', '.join(tool_names)}"
        )

    def call_tool(self, tool_name: str, args: dict) -> str:
        """Dispatch a tool call to the background event loop and block for result."""
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
                # Keep the loop alive for subsequent tool calls
                self._loop.run_forever()

    async def _connect_and_discover(self):
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        if self._url:
            transport = streamable_http_client(self._url)
        elif self._command:
            from mcp import StdioServerParameters
            params = StdioServerParameters(
                command=self._command,
                args=self._args,
                env=self._env,
            )
            transport = stdio_client(params)
        else:
            raise ValueError("Either 'command' (stdio) or 'url' (HTTP) is required")

        self._transport = transport
        read, write = await transport.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._session = session

        # Discover tools
        result = await session.list_tools()
        self.tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema if hasattr(t, 'inputSchema') else (t.input_schema if hasattr(t, 'input_schema') else {}),
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
            self._loop.stop()


# ═════════════════════════════════════════════════════════════════════════════
# Mock servers (offline / teaching)
# ═════════════════════════════════════════════════════════════════════════════

def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {"name": "search", "description": "Search documentation. (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
            {"name": "get_version", "description": "Get API version. (readOnly)",
             "inputSchema": {"type": "object", "properties": {},
                             "required": []}},
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        },
    )
    return client


def _mock_server_deploy():
    client = MCPClient("deploy")
    client.register(
        tool_defs=[
            {"name": "trigger",
             "description": "Trigger a deployment. (destructive — requires approval)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
            {"name": "status", "description": "Check deployment status. (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        },
    )
    return client


MOCK_SERVERS = {
    "docs": _mock_server_docs,
    "deploy": _mock_server_deploy,
}


# ═════════════════════════════════════════════════════════════════════════════
# connect_mcp tool
# ═════════════════════════════════════════════════════════════════════════════

def connect_mcp(name: str, *,
                command: str | None = None,
                args: list[str] | None = None,
                url: str | None = None,
                env: dict[str, str] | None = None) -> str:
    """Connect to an MCP server.

    - If *command* is given: launch as a stdio subprocess.
    - If *url* is given: connect via HTTP.
    - If neither: look up *name* in MOCK_SERVERS.

    The server's tools become available as mcp__<server>__<tool>.
    """
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"

    if command or url:
        client = RealMCPClient(
            name, command=command, args=args, url=url, env=env,
        )
        result = client.connect()
        if "timed out" in result or result.startswith("MCP '"):
            return result  # error message
        mcp_clients[name] = client
        return result

    # Mock fallback
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return (
            f"Unknown server '{name}'. Mock servers: {available}. "
            f"For a real server, pass command= or url=."
        )
    client = factory()
    mcp_clients[name] = client
    tool_names = [t["name"] for t in client.tools]
    print(f"  \033[31m[mcp] connected (mock): {name} → {tool_names}\033[0m")
    return (
        f"Connected to MCP server '{name}' (mock). "
        f"Discovered {len(client.tools)} tools: {', '.join(tool_names)}"
    )
