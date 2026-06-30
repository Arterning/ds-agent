#!/usr/bin/env python3
"""
Mock MCP stdio server — deploy (trigger + status).

Referenced by .mcp.json.
"""
import json, sys


TOOLS = [
    {"name": "trigger",
     "description": "Trigger a deployment. (destructive — requires approval in real CC)",
     "inputSchema": {"type": "object",
                     "properties": {"service": {"type": "string"}},
                     "required": ["service"]}},
    {"name": "status", "description": "Check deployment status. (readOnly)",
     "inputSchema": {"type": "object",
                     "properties": {"service": {"type": "string"}},
                     "required": ["service"]}},
]

HANDLERS = {
    "trigger": lambda args: [{"type": "text", "text": f"[deploy] Triggered: {args.get('service', '')}"}],
    "status": lambda args: [{"type": "text", "text": f"[deploy] {args.get('service', '')}: running (v1.4.2)"}],
}


def handle(req: dict) -> dict | None:
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-deploy", "version": "1.0.0"},
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
