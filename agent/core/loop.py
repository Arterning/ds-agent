"""
Main agent loop — the core execution cycle.

Each iteration:
1. inject cron / background notifications
2. prepare context (compaction budget)
3. call the LLM (OpenAI chat completions)
4. execute tool calls → push role=tool messages
5. loop until the model stops without tool_calls
"""

import json, threading

from agent.config import (
    client,
    DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES, CONTINUATION_PROMPT,
)
from agent.core.prompt import assemble_system_prompt
from agent.core.compaction import (
    compact_history, reactive_compact,
    tool_result_budget, snip_compact, micro_compact,
    estimate_size,
)
from agent.core.recovery import RecoveryState, with_retry, is_prompt_too_long_error
from agent.core.context import update_context
from agent.tools.registry import assemble_tool_pool
from agent.systems.background import (
    should_run_background, start_background_task,
    collect_background_results,
)
from agent.systems.cron import consume_cron_queue
from agent.hooks import trigger_hooks
from agent.utils import terminal_print, call_tool_handler


agent_lock = threading.Lock()
rounds_since_todo = 0


# ── helpers ─────────────────────────────────────────────────────────────────

def _openai_tools(tool_defs: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool defs → OpenAI function tool defs."""
    out = []
    for t in tool_defs:
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


def _parse_tool_arguments(tc) -> dict:
    """Parse arguments from a tool_call dict (may be JSON string or already dict)."""
    args = tc.get("arguments", {})
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args or {}


def _inject_background_notifications(messages: list):
    """Inject completed background-task results as plain-text user messages."""
    notes = collect_background_results()
    for note in notes:
        messages.append({"role": "user", "content": note})


# ── main loop ───────────────────────────────────────────────────────────────

def _call_llm(messages: list, context: dict, tools: list,
              state: RecoveryState, max_tokens: int):
    """Call OpenAI chat completions. System prompt is prepended as a role=system message."""
    from agent.utils import sanitize_json
    system = assemble_system_prompt(context)
    full_messages = sanitize_json([{"role": "system", "content": system}] + messages)
    openai_tools = _openai_tools(tools)

    def _do():
        return client.chat.completions.create(
            model=state.current_model,
            messages=full_messages,
            tools=openai_tools or None,
            max_tokens=max_tokens,
        )

    return with_retry(_do, state)


def agent_loop(messages: list, context: dict):
    global rounds_since_todo
    tools, handlers = assemble_tool_pool()
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    while True:
        # --- inject scheduled / background work ---
        for job in consume_cron_queue():
            messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
            print(f"  \033[35m[cron inject] {job.prompt[:60]}\033[0m")

        _inject_background_notifications(messages)

        if rounds_since_todo >= 3:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0

        # --- compaction budget ---
        messages[:] = tool_result_budget(messages)
        messages[:] = snip_compact(messages)
        messages[:] = micro_compact(messages)
        if estimate_size(messages) > 50_000:
            messages[:] = compact_history(messages)

        context = update_context(context, messages)
        tools, handlers = assemble_tool_pool()

        # --- call model ---
        try:
            response = _call_llm(messages, context, tools, state, max_tokens)
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            messages.append({"role": "assistant",
                             "content": f"[Error] {type(e).__name__}"})
            return

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        assistant_msg = choice.message

        # --- handle max_tokens / truncation ---
        if finish_reason == "length":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                continue
            messages.append({"role": "assistant", "content": assistant_msg.content or ""})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                continue
            return

        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False

        # --- store assistant message ---
        stored_msg = {
            "role": "assistant",
            "content": assistant_msg.content,
        }
        if assistant_msg.tool_calls:
            stored_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(stored_msg)

        # --- check for stop ---
        if not assistant_msg.tool_calls:
            trigger_hooks("Stop", messages)
            return

        # --- execute tool calls; each result is a role=tool message ---
        compacted_now = False

        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            tool_args = _parse_tool_arguments({"arguments": tc.function.arguments})
            tool_call_id = tc.id

            print(f"\033[36m> {tool_name}\033[0m")

            # --- compact special-case ---
            if tool_name == "compact":
                messages[:] = compact_history(messages)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                compacted_now = True
                break

            # --- permission hook ---
            class ToolBlock:
                pass
            block = ToolBlock()
            block.name = tool_name
            block.input = tool_args
            block.id = tool_call_id

            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": str(blocked),
                })
                continue

            # --- background check ---
            if should_run_background(tool_name, tool_args):
                bg_id = start_background_task(tool_name, tool_args, tool_call_id, handlers)
                output = (f"[Background task {bg_id} started] "
                          "Result will arrive as a task_notification.")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": output,
                })
                continue

            # --- execute ---
            handler = handlers.get(tool_name)
            output = call_tool_handler(handler, tool_args, tool_name)
            trigger_hooks("PostToolUse", block, output)
            # Sanitize surrogates before printing
            safe_out = str(output).encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
            print(safe_out[:300])

            if tool_name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output,
            })

        if compacted_now:
            continue


def print_turn_assistants(messages: list, turn_start: int):
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            safe = content.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
            terminal_print(safe)
