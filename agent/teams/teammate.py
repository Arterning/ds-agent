"""
Teammate thread — autonomous agent running in its own thread with a restricted
tool set.  Communicates with the lead agent via the message bus.

Key behaviours:
- Claims tasks, respects worktree directories
- submit_plan gates further work until lead approves
- Idle-polling for new work when nothing is active
"""

import json, re, time, threading
from pathlib import Path

from agent.config import (
    MODEL, client, WORKDIR, WORKTREES_DIR,
    IDLE_POLL_INTERVAL, active_teammates,
)
from agent.teams.bus import BUS
from agent.teams.protocol import ProtocolState, new_request_id, pending_requests
from agent.systems.tasks import (
    list_tasks, load_task, claim_task, complete_task,
)
from agent.utils import (
    call_tool_handler, has_tool_use, extract_tool_calls,
    extract_text, terminal_print,
)
from agent.tools.bash import run_bash
from agent.tools.file import run_read, run_write
from agent.teams.autonomous import idle_poll


def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    if name in active_teammates:
        return f"Teammate '{name}' already exists"

    protocol_ctx = {"waiting_plan": None}
    system = (
        f"You are '{name}', a {role}. "
        f"Use tools to complete tasks. "
        f"If a task has a worktree, work in that directory."
    )

    def _handle_inbox_message(msg: dict, messages: list) -> bool:
        msg_type = msg.get("type", "message")
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")
        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down.",
                     "shutdown_response",
                     {"request_id": req_id, "approve": True})
            return True
        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if req_id == protocol_ctx["waiting_plan"]:
                protocol_ctx["waiting_plan"] = None
            messages.append({
                "role": "user",
                "content": (
                    "[Plan approved]" if approve
                    else f"[Plan rejected] {msg['content']}"
                ),
            })
        return False

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

    def run():
        wt_ctx = {"path": None}

        def _wt_cwd():
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str:
            return run_bash(command, cwd=_wt_cwd())

        def _run_read(path: str) -> str:
            return run_read(path, cwd=_wt_cwd())

        def _run_write(path: str, content: str) -> str:
            return run_write(path, content, cwd=_wt_cwd())

        def _run_list_tasks():
            tasks = list_tasks()
            if not tasks:
                return "No tasks."
            return "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]"
                + (f" (wt:{t.worktree})" if t.worktree else "")
                for t in tasks
            )

        def _run_claim_task(task_id: str):
            result = claim_task(task_id, owner=name)
            if "Claimed" in result:
                task = load_task(task_id)
                wt_ctx["path"] = (
                    str(WORKTREES_DIR / task.worktree)
                    if task.worktree else None
                )
            return result

        def _run_complete_task(task_id: str):
            result = complete_task(task_id)
            wt_ctx["path"] = None
            return result

        sub_tools = [
            {"name": "bash", "description": "Run a shell command.",
             "input_schema": {"type": "object",
                              "properties": {"command": {"type": "string"}},
                              "required": ["command"]}},
            {"name": "read_file", "description": "Read file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "limit": {"type": "integer"},
                                             "offset": {"type": "integer"}},
                              "required": ["path"]}},
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["path", "content"]}},
            {"name": "send_message",
             "description": "Send message to another agent.",
             "input_schema": {"type": "object",
                              "properties": {"to": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["to", "content"]}},
            {"name": "submit_plan",
             "description": "Submit a plan for Lead approval.",
             "input_schema": {"type": "object",
                              "properties": {"plan": {"type": "string"}},
                              "required": ["plan"]}},
            {"name": "list_tasks",
             "description": "List all tasks.",
             "input_schema": {"type": "object", "properties": {},
                              "required": []}},
            {"name": "claim_task",
             "description": "Claim a pending task.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
            {"name": "complete_task",
             "description": "Mark an in-progress task as completed.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
        ]

        sub_handlers = {
            "bash": _run_bash,
            "read_file": _run_read,
            "write_file": _run_write,
            "send_message": lambda to, content: (
                BUS.send(name, to, content), "Sent"
            )[1],
            "list_tasks": _run_list_tasks,
            "claim_task": _run_claim_task,
            "complete_task": _run_complete_task,
        }

        messages = [{"role": "user", "content": prompt}]
        openai_tools = _openai_tools(sub_tools)

        while True:
            if len(messages) <= 3:
                messages.insert(0, {
                    "role": "user",
                    "content": (
                        f"<identity>You are '{name}', role: {role}. "
                        f"Continue your work.</identity>"
                    ),
                })

            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    stopped = _handle_inbox_message(msg, messages)
                    if stopped:
                        should_shutdown = True
                        break
                if should_shutdown:
                    break
                if protocol_ctx["waiting_plan"]:
                    time.sleep(IDLE_POLL_INTERVAL)
                    continue
                if inbox and not should_shutdown:
                    non_protocol = [
                        m for m in inbox if m.get("type") == "message"
                    ]
                    if non_protocol:
                        messages.append({
                            "role": "user",
                            "content": "<inbox>" + json.dumps(non_protocol) + "</inbox>",
                        })

                # --- call model ---
                try:
                    response = client.chat.completions.create(
                        model=MODEL,
                        messages=[{"role": "system", "content": system}] + messages[-20:],
                        tools=openai_tools,
                        max_tokens=8000,
                    )
                except Exception:
                    break

                choice = response.choices[0]
                assistant_msg = choice.message

                # Store
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

                # --- execute tool calls ---
                results = []
                for tc in assistant_msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    if tool_name == "submit_plan":
                        output = _submit_plan(name, tool_args.get("plan", ""))
                        match = re.search(r"\((req_\d+)\)", output)
                        protocol_ctx["waiting_plan"] = (
                            match.group(1) if match else output
                        )
                    else:
                        handler = sub_handlers.get(tool_name)
                        output = call_tool_handler(handler, tool_args, tool_name)

                    results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": str(output),
                    })
                    if protocol_ctx["waiting_plan"]:
                        break

                messages.append({"role": "user", "content": results})
                if protocol_ctx["waiting_plan"]:
                    break

            if should_shutdown:
                break
            if protocol_ctx["waiting_plan"]:
                continue

            idle_result = idle_poll(name, messages, name, role, wt_ctx)
            if idle_result in ("shutdown", "timeout"):
                break

        # --- final result ---
        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    summary = content.strip()
                    break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    return f"Teammate '{name}' spawned as {role}"


def _submit_plan(from_name: str, plan: str) -> str:
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="plan_approval",
        sender=from_name, target="lead",
        status="pending", payload=plan,
    )
    BUS.send(from_name, "lead", plan,
             "plan_approval_request",
             {"request_id": req_id})
    return f"Plan submitted ({req_id})"
