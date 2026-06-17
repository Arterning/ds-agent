"""
Context (memory) helpers.

Reads the MEMORY.md file and snapshots active teammates / MCP servers so the
system prompt stays up-to-date.
"""

from agent.config import MEMORY_INDEX, mcp_clients, active_teammates


def update_context(context: dict, _messages: list) -> dict:
    memories = ""
    if MEMORY_INDEX.exists():
        memories = MEMORY_INDEX.read_text()[:2000]
    return {
        "memories": memories,
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }
