"""
Subagent — a short-lived mini agent with restricted tools.

Spawned by the main loop via the `task` tool.  Runs its own inner loop
and returns only a final text summary.
"""

import json

from agent.config import MODEL, client, WORKDIR
from agent.tools.bash import run_bash
from agent.tools.file import run_read, run_write, run_edit, run_glob
from agent.hooks import trigger_hooks
from agent.utils import call_tool_handler, extract_text, has_tool_use, sanitize_json

SUB_SYSTEM = (
    f"You are a coding subagent at {WORKDIR}. "
    "Complete the task, then return a concise final summary. "
    "Do not spawn more agents."
)

SUB_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "limit": {"type": "integer"},
                                     "offset": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "old_text": {"type": "string"},
                                     "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
]

SUB_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
}


def _openai_tools(defs: list[dict]) -> list[dict]:
    out = []
    for t in defs:
        schema = t.get("input_schema") or t.get("parameters") or {}
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": {
                    "type": schema.get("type", "object"),
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        })
    return out


def spawn_subagent(description: str) -> str:
    messages = [{"role": "user", "content": description}]
    openai_tools = _openai_tools(SUB_TOOLS)

    for _ in range(30):
        response = client.chat.completions.create(
            model=MODEL,
            messages=sanitize_json([{"role": "system", "content": SUB_SYSTEM}] + messages),
            tools=openai_tools,
            max_tokens=8000,
        )

        choice = response.choices[0]
        assistant_msg = choice.message

        stored = {"role": "assistant", "content": assistant_msg.content}
        if assistant_msg.tool_calls:
            stored["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(stored)

        if not assistant_msg.tool_calls:
            break

        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # Build synthetic block for hooks
            class _Block:
                pass
            block = _Block()
            block.name = tool_name
            block.input = tool_args
            block.id = tc.id

            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                output = str(blocked)
            else:
                handler = SUB_HANDLERS.get(tool_name)
                output = call_tool_handler(handler, tool_args, tool_name)
                trigger_hooks("PostToolUse", block, output)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(output),
            })

    for msg in reversed(messages):
        if msg["role"] == "assistant":
            text = msg.get("content", "")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return "Subagent finished without a text summary."
