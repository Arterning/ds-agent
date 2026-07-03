"""
System-prompt assembly.

The prompt is rebuilt each turn from live context (skills, MCP servers,
active teammates, current time).
"""

from datetime import datetime

from agent.tools.skill import list_skills
from agent.config import WORKDIR, mcp_clients

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: bash, read_file, write_file, edit_file, glob, "
             "todo_write, task, load_skill, compact, "
             "web_search, web_fetch, "
             "create_task, list_tasks, get_task, claim_task, complete_task, "
             "schedule_cron, list_crons, cancel_cron, "
             "spawn_teammate, send_message, check_inbox, "
             "request_shutdown, request_plan, review_plan, "
             "create_worktree, remove_worktree, keep_worktree, "
             "connect_mcp. "
             "MCP servers in .mcp.json are auto-connected at startup. "
             "To connect a new server at runtime pass command + args (stdio) or url (HTTP). "
             "MCP tools are prefixed mcp__{server}__{tool}.",
    "workspace": f"Working directory: {WORKDIR}",
    "memory": "Relevant memories are injected below when available.",
}


def assemble_system_prompt(context: dict) -> str:
    sections = [
        PROMPT_SECTIONS["identity"],
        PROMPT_SECTIONS["tools"],
        PROMPT_SECTIONS["workspace"],
    ]
    sections.append(f"Current time: {datetime.now().isoformat(timespec='seconds')}")
    sections.append(
        "Skills catalog:\n" + list_skills() +
        "\nUse load_skill(name) when a skill is relevant."
    )
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)
