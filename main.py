#!/usr/bin/env python3
"""
ds-agent — a comprehensive coding agent.

Run:  python main.py
Need: pip install openai python-dotenv pyyaml
      + .env with DEEPSEEK_API_KEY
      (optionally DEEPSEEK_BASE_URL and MODEL_ID)
"""

import threading, time

from agent.config import CLI_ACTIVE, PROMPT
from agent.core.loop import agent_loop, print_turn_assistants
from agent.core.context import update_context
from agent.systems.cron import consume_cron_queue, cron_scheduler_loop
from agent.teams.protocol import consume_lead_inbox
from agent.hooks import trigger_hooks
from agent.tools.mcp import init_mcp

# Ensure logging hooks are loaded
import agent.hooks.logging  # noqa: F401


agent_lock = threading.Lock()


def cron_autorun_loop(history: list, context: dict):
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                history.append({
                    "role": "user",
                    "content": f"[Scheduled] {job.prompt}",
                })
                print(f"  \033[35m[cron auto] {job.prompt[:60]}\033[0m")
            agent_loop(history, context)
            context.update(update_context(context, history))
            print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    CLI_ACTIVE = True
    print("ds-agent: comprehensive coding agent (DeepSeek)")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    # Auto-connect all MCP servers listed in .mcp.json
    init_mcp()
    print()

    history: list = []
    context = update_context({}, [])

    threading.Thread(
        target=cron_autorun_loop,
        args=(history, context),
        daemon=True,
    ).start()

    while True:
        try:
            query = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        history.append({"role": "user", "content": query})
        with agent_lock:
            agent_loop(history, context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)

        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            def inbox_label(msg):
                req_id = msg.get("metadata", {}).get("request_id", "")
                suffix = f" req:{req_id}" if req_id else ""
                return f"{msg.get('type', 'message')}{suffix}"

            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: "
                f"{m['content'][:200]}" for m in inbox
            )
            history.append({
                "role": "user",
                "content": f"[Inbox]\n{inbox_text}",
            })
        print()
