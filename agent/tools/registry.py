"""
Tool registry — the single source of truth for all builtin tool definitions
and their handlers.  MCP tools are merged in at runtime by assemble_tool_pool().
"""

from agent.tools.bash import run_bash
from agent.tools.file import run_read, run_write, run_edit, run_glob
from agent.tools.todo import run_todo_write
from agent.tools.subagent import spawn_subagent
from agent.tools.skill import load_skill
from agent.tools.mcp import normalize_mcp_name, mcp_clients

from agent.systems.tasks import (
    create_task as _create, list_tasks as _list, get_task_json,
    claim_task as _claim, complete_task as _complete,
)
from agent.systems.worktree import (
    create_worktree as _create_wt, remove_worktree as _remove_wt,
    keep_worktree as _keep_wt,
)
from agent.systems.cron import run_schedule_cron, run_list_crons, run_cancel_cron
from agent.teams.teammate import spawn_teammate_thread
from agent.teams.bus import BUS
from agent.teams.protocol import (
    consume_lead_inbox, run_request_shutdown,
    run_request_plan, run_review_plan,
)
from agent.tools.mcp import connect_mcp
from agent.tools.web import web_search, web_fetch


# ── Tool-facing wrappers for task tools ────────────────────────────────────

def run_create_task(subject: str, description: str = "",
                    blockedBy: list[str] | None = None) -> str:
    task = _create(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
    return f"Created {task.id}: {task.subject}{deps}"


def run_list_tasks() -> str:
    tasks = _list()
    if not tasks:
        return "No tasks."
    return "\n".join(
        f"  {t.id}: {t.subject} [{t.status}]"
        + (f" (wt:{t.worktree})" if t.worktree else "")
        for t in tasks
    )


def run_get_task(task_id: str) -> str:
    try:
        return get_task_json(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


def run_claim_task(task_id: str) -> str:
    try:
        return _claim(task_id, owner="agent")
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


def run_complete_task(task_id: str) -> str:
    try:
        return _complete(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


# ── Teammate-facing wrappers ───────────────────────────────────────────────

def run_spawn_teammate(name: str, role: str, prompt: str) -> str:
    return spawn_teammate_thread(name, role, prompt)


def run_send_message(to: str, content: str) -> str:
    BUS.send("lead", to, content)
    return f"Sent to {to}"


def run_check_inbox() -> str:
    msgs = consume_lead_inbox(route_protocol=True)
    if not msgs:
        return "(inbox empty)"
    lines = []
    for m in msgs:
        meta = m.get("metadata", {})
        req_id = meta.get("request_id", "")
        tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
        lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
    return "\n".join(lines)


# ── Worktree wrappers ──────────────────────────────────────────────────────

def run_create_worktree(name: str, task_id: str = "") -> str:
    return _create_wt(name, task_id)


def run_remove_worktree(name: str, discard_changes: bool = False) -> str:
    return _remove_wt(name, discard_changes)


def run_keep_worktree(name: str) -> str:
    return _keep_wt(name)


# ── MCP wrapper ────────────────────────────────────────────────────────────

def run_connect_mcp(name: str, command: str | None = None,
                    args: list[str] | None = None,
                    url: str | None = None,
                    env: dict[str, str] | None = None) -> str:
    return connect_mcp(name, command=command, args=args, url=url, env=env)


# ── Tool definitions (Anthropic-style schemas) ─────────────────────────────

BUILTIN_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"},
                                     "run_in_background": {"type": "boolean"}},
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
    {"name": "todo_write",
     "description": "Create and manage a task list for the current session.",
     "input_schema": {"type": "object",
                      "properties": {"todos": {"type": "array",
                          "items": {"type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "status": {"type": "string",
                                                   "enum": ["pending", "in_progress", "completed"]}},
                                    "required": ["content", "status"]}}},
                      "required": ["todos"]}},
    {"name": "task",
     "description": "Launch a focused subagent. Returns only its final summary.",
     "input_schema": {"type": "object",
                      "properties": {"description": {"type": "string"}},
                      "required": ["description"]}},
    {"name": "load_skill",
     "description": "Load the full content of a skill by name.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "compact",
     "description": "Summarize earlier conversation and continue with compacted context.",
     "input_schema": {"type": "object",
                      "properties": {"focus": {"type": "string"}},
                      "required": []}},
    {"name": "create_task", "description": "Create a task.",
     "input_schema": {"type": "object",
                      "properties": {"subject": {"type": "string"},
                                     "description": {"type": "string"},
                                     "blockedBy": {"type": "array",
                                                   "items": {"type": "string"}}},
                      "required": ["subject"]}},
    {"name": "list_tasks", "description": "List all tasks.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_task", "description": "Get full task details.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "claim_task", "description": "Claim a pending task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "complete_task", "description": "Complete an in-progress task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "schedule_cron",
     "description": ("Schedule a cron job. cron is 5-field: min hour dom "
                     "month dow. For one-shot reminders, compute the target "
                     "minute and set recurring=false."),
     "input_schema": {"type": "object",
                      "properties": {"cron": {"type": "string"},
                                     "prompt": {"type": "string"},
                                     "recurring": {"type": "boolean"},
                                     "durable": {"type": "boolean"}},
                      "required": ["cron", "prompt"]}},
    {"name": "list_crons", "description": "List registered cron jobs.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "cancel_cron", "description": "Cancel a cron job by ID.",
     "input_schema": {"type": "object",
                      "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "spawn_teammate", "description": "Spawn an autonomous teammate.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "role": {"type": "string"},
                                     "prompt": {"type": "string"}},
                      "required": ["name", "role", "prompt"]}},
    {"name": "send_message", "description": "Send message to a teammate.",
     "input_schema": {"type": "object",
                      "properties": {"to": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["to", "content"]}},
    {"name": "check_inbox",
     "description": "Check inbox for messages and protocol responses.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "request_shutdown",
     "description": "Request a teammate to shut down.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"}},
                      "required": ["teammate"]}},
    {"name": "request_plan",
     "description": "Ask a teammate to submit a plan.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"},
                                     "task": {"type": "string"}},
                      "required": ["teammate", "task"]}},
    {"name": "review_plan",
     "description": "Approve or reject a submitted plan.",
     "input_schema": {"type": "object",
                      "properties": {"request_id": {"type": "string"},
                                     "approve": {"type": "boolean"},
                                     "feedback": {"type": "string"}},
                      "required": ["request_id", "approve"]}},
    {"name": "create_worktree",
     "description": "Create an isolated git worktree.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "task_id": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "remove_worktree",
     "description": "Remove a worktree. Refuses if changes exist.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "discard_changes": {"type": "boolean"}},
                      "required": ["name"]}},
    {"name": "keep_worktree",
     "description": "Keep a worktree for manual review.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "connect_mcp",
     "description": (
         "Connect to an MCP server at runtime. Servers in .mcp.json are "
         "auto-connected at startup. Use 'command'+'args' for a stdio "
         "subprocess or 'url' for HTTP. Tools become mcp__<server>__<tool>."
     ),
     "input_schema": {"type": "object",
                      "properties": {
                          "name": {"type": "string",
                                   "description": "Logical name for this MCP server"},
                          "command": {"type": "string",
                                      "description": "Executable to launch (stdio mode)"},
                          "args": {"type": "array",
                                   "items": {"type": "string"},
                                   "description": "Arguments for the command"},
                          "url": {"type": "string",
                                  "description": "HTTP endpoint URL (HTTP mode)"},
                          "env": {"type": "object",
                                  "description": "Extra environment variables"},
                      },
                      "required": ["name"]}},
    {"name": "web_search",
     "description": "Search the web via DuckDuckGo. Returns JSON with title, url, snippet.",
     "input_schema": {"type": "object",
                      "properties": {
                          "query": {"type": "string", "description": "Search query"},
                          "max_results": {"type": "integer", "description": "Max results (1-10)"},
                      },
                      "required": ["query"]}},
    {"name": "web_fetch",
     "description": "Fetch a URL and extract readable plain text (up to 50k chars).",
     "input_schema": {"type": "object",
                      "properties": {
                          "url": {"type": "string", "description": "URL to fetch (https://...)"},
                      },
                      "required": ["url"]}},
]

BUILTIN_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
    "todo_write": run_todo_write, "task": spawn_subagent,
    "load_skill": load_skill,
    "create_task": run_create_task, "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task, "complete_task": run_complete_task,
    "schedule_cron": run_schedule_cron,
    "list_crons": run_list_crons,
    "cancel_cron": run_cancel_cron,
    "spawn_teammate": run_spawn_teammate,
    "send_message": run_send_message, "check_inbox": run_check_inbox,
    "request_shutdown": run_request_shutdown,
    "request_plan": run_request_plan, "review_plan": run_review_plan,
    "create_worktree": run_create_worktree,
    "remove_worktree": run_remove_worktree,
    "keep_worktree": run_keep_worktree,
    "connect_mcp": run_connect_mcp,
    "web_search": web_search,
    "web_fetch": web_fetch,
}


def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Merge builtin tools + all connected MCP tools into one pool."""
    tools = list(BUILTIN_TOOLS)
    handlers = dict(BUILTIN_HANDLERS)
    for server_name, mcp in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            handlers[prefixed] = (
                lambda *, c=mcp, t=tool_def["name"], **kw: c.call_tool(t, kw)
            )
    return tools, handlers
