"""
Shared helpers used across the agent.

All functions are pure or only read config — no side-effects on import.
"""

import threading
from pathlib import Path

from agent.config import WORKDIR, PROMPT, CLI_ACTIVE, READLINE_AVAILABLE


def terminal_print(text: str):
    """Print without clobbering the CLI input line when called from background threads."""
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            import readline
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)


def safe_path(p: str, cwd: Path | None = None) -> Path:
    """Resolve *p* inside *cwd* (or WORKDIR).  Raises if the result escapes."""
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def call_tool_handler(handler, args: dict, name: str) -> str:
    """Invoke *handler* with *args*; return the string result or an error message."""
    if not handler:
        return f"Unknown: {name}"
    try:
        return handler(**(args or {}))
    except TypeError as e:
        return f"Error: {e}"


# ── OpenAI message helpers ──────────────────────────────────────────────────

def has_tool_use(content) -> bool:
    """Return True when the assistant message has pending tool_calls."""
    if isinstance(content, list):
        return any(has_tool_use(block) for block in content)
    return getattr(content, "tool_calls", None) is not None and bool(content.tool_calls)


def extract_text(content) -> str:
    """Pull the plain-text portion out of an assistant message."""
    if not isinstance(content, list):
        return getattr(content, "content", "") or ""
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        else:
            txt = getattr(block, "text", None)
            if txt:
                parts.append(txt)
    return "\n".join(parts).strip()


def extract_tool_calls(content) -> list[dict]:
    """Extract tool-call dicts (normalised form) from an assistant message."""
    if not isinstance(content, list):
        tc = getattr(content, "tool_calls", None) or []
        return [
            {"id": t.id, "name": t.function.name,
             "arguments": t.function.arguments}
            for t in tc
        ]
    calls: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append({
                "id": block.get("id"),
                "name": block.get("name"),
                "arguments": block.get("input", {}),
            })
        else:
            tc = getattr(block, "tool_calls", None) or []
            for t in tc:
                calls.append({
                    "id": t.id, "name": t.function.name,
                    "arguments": t.function.arguments,
                })
    return calls
