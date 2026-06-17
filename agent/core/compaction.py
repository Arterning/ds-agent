"""
Context compaction — budget, snip, micro, full compact, reactive compact.

Layered strategy:
1. tool_result_budget — cap oversized tool-result content
2. snip_compact         — remove a middle chunk of old messages
3. micro_compact        — stub out older tool results
4. compact_history      — summarise via LLM
5. reactive_compact     — summarise + keep tail after prompt-too-long error

All functions operate on OpenAI-format message lists (role=tool for results).
"""

import json, time
from pathlib import Path

from agent.config import (
    TRANSCRIPT_DIR, TOOL_RESULTS_DIR,
    CONTEXT_LIMIT, KEEP_RECENT_TOOL_RESULTS, PERSIST_THRESHOLD,
    MODEL, client,
)
from agent.utils import extract_text, sanitize, sanitize_json


def estimate_size(messages: list) -> int:
    return len(json.dumps(sanitize_json(messages), default=str))


def message_has_tool_use(message: dict) -> bool:
    """Return True when an assistant message has pending tool_calls."""
    if message.get("role") != "assistant":
        return False
    # Check message-level tool_calls key (OpenAI format)
    if message.get("tool_calls"):
        return True
    # Also check nested inside content (for Anthropic-style blocks if any remain)
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_calls"):
                return True
    return False


def is_tool_result_message(message: dict) -> bool:
    """Return True for role=tool messages (OpenAI format) or legacy user messages
    containing tool_result blocks."""
    if message.get("role") == "tool":
        return True
    # Legacy support: user message with tool_result blocks inside
    if message.get("role") == "user":
        content = message.get("content")
        if isinstance(content, list):
            return any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
    return False


def collect_tool_results(messages: list) -> list[dict]:
    """Return every role=tool message in order."""
    return [msg for msg in messages if msg.get("role") == "tool"]


def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output)
    return (f"<persisted-output>\nFull output: {path}\n"
            f"Preview:\n{output[:2000]}\n</persisted-output>")


def tool_result_budget(messages: list, max_bytes: int = 200_000) -> list:
    """Persist the largest tool-result contents to disk if the last batch exceeds max_bytes."""
    if not messages:
        return messages
    # Find the contiguous tail of role=tool messages
    tool_msgs = []
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "tool":
            tool_msgs.insert(0, messages[i])
        else:
            break
    if not tool_msgs:
        return messages
    total = sum(len(str(m.get("content", ""))) for m in tool_msgs)
    if total <= max_bytes:
        return messages
    for m in sorted(tool_msgs,
                    key=lambda m: len(str(m.get("content", ""))),
                    reverse=True):
        if total <= max_bytes:
            break
        text = str(m.get("content", ""))
        m["content"] = persist_large_output(
            m.get("tool_call_id", "unknown"), text)
        total = sum(len(str(mm.get("content", ""))) for mm in tool_msgs)
    return messages


def snip_compact(messages: list, max_messages: int = 50) -> list:
    if len(messages) <= max_messages:
        return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 3)
    if head_end > 0 and message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and is_tool_result_message(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    return (messages[:head_end]
            + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
            + messages[tail_start:])


def micro_compact(messages: list) -> list:
    """Stub out older tool-result contents so the context stays under budget."""
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for m in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(str(m.get("content", ""))) > 120:
            m["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(sanitize_json(msg), default=str) + "\n")
    return path


def summarize_history(messages: list) -> str:
    conversation = json.dumps(sanitize_json(messages), default=str)[:80000]
    prompt = ("Summarize this coding-agent conversation so work can continue. "
              "Preserve current goal, key findings, changed files, remaining work, "
              "and user constraints.\n\n" + conversation)
    response = client.chat.completions.create(
        model=MODEL,
        messages=sanitize_json([{"role": "user", "content": prompt}]),
        max_tokens=2000,
    )
    return extract_text(response.choices[0].message) or "(empty summary)"


def compact_history(messages: list) -> list:
    transcript = write_transcript(messages)
    print(f"  \033[36m[compact] transcript saved: {transcript}\033[0m")
    summary = summarize_history(messages)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]


def reactive_compact(messages: list) -> list:
    transcript = write_transcript(messages)
    print(f"  \033[31m[reactive compact] transcript saved: {transcript}\033[0m")
    try:
        summary = summarize_history(messages)
    except Exception:
        summary = "Earlier conversation was trimmed after a prompt-too-long error."
    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    return [
        {"role": "user", "content": f"[Reactive compact]\n\n{summary}"},
        *messages[tail_start:],
    ]
