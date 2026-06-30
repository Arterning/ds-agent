#!/usr/bin/env python3
"""
Minimal MCP stdio server for testing ds-agent's MCP client.

Tools: echo, add, now

Run:   uv run python mcp_server.py
"""
import json, sys
from datetime import datetime


def handle_request(req: dict) -> dict | None:
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "demo-server", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {"tools": [
                {"name": "echo", "description": "Echo back the message",
                 "inputSchema": {"type": "object",
                                 "properties": {"message": {"type": "string"}},
                                 "required": ["message"]}},
                {"name": "add", "description": "Add two numbers",
                 "inputSchema": {"type": "object",
                                 "properties": {"a": {"type": "number"},
                                                "b": {"type": "number"}},
                                 "required": ["a", "b"]}},
                {"name": "now", "description": "Get current server time",
                 "inputSchema": {"type": "object", "properties": {},
                                 "required": []}},
            ]},
        }
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name == "echo":
            text = arguments.get("message", "")
            result = [{"type": "text", "text": f"[demo] {text}"}]
        elif tool_name == "add":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            result = [{"type": "text", "text": str(a + b)}]
        elif tool_name == "now":
            result = [{"type": "text", "text": datetime.now().isoformat()}]
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": result}}

    # ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}

    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except BrokenPipeError:
            break


if __name__ == "__main__":
    main()
