#!/usr/bin/env python3
"""
Mock MCP stdio server — docs (search + get_version).

Referenced by .mcp.json.
"""
import json, sys


TOOLS = [
    {"name": "search", "description": "Search documentation. (readOnly)",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"}},
                     "required": ["query"]}},
    {"name": "get_version", "description": "Get API version. (readOnly)",
     "inputSchema": {"type": "object", "properties": {},
                     "required": []}},
]

HANDLERS = {
    "search": lambda args: [{"type": "text", "text": f"[docs] Found 3 results for '{args.get('query', '')}'"}],
    "get_version": lambda _: [{"type": "text", "text": "[docs] API v2.1.0"}],
}


def handle(req: dict) -> dict | None:
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-docs", "version": "1.0.0"},
        }}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if not handler:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {name}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": handler(args)}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {method}"}}


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            resp = handle(json.loads(line))
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except BrokenPipeError:
            break


if __name__ == "__main__":
    main()
