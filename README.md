# ds-agent

A comprehensive coding agent powered by **DeepSeek**.

Based on [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) chapter 20, refactored into modular packages and ported from Anthropic to the OpenAI-compatible DeepSeek API.

## Features

- **Agent loop** — multi-turn tool-calling with context compaction
- **Task system** — file-backed tasks with ownership, status, and dependencies
- **Git worktrees** — isolated per-task directories with change tracking
- **Teammates** — autonomous sub-agents that claim tasks and communicate
- **Plan approval protocol** — teammates gate on lead approval before destructive work
- **Subagent** — short-lived mini-agent for focused tasks
- **Cron scheduler** — 5-field cron with durable persistence
- **Background tasks** — slow bash commands run async, results injected later
- **Skills** — Markdown playbooks under `skills/<name>/SKILL.md`
- **MCP** — late-bound tool servers (mock `docs` and `deploy` included)
- **Permission hooks** — deny-list, destructive confirmation, path containment
- **Error recovery** — retry with backoff, 429/529 handling, model fallback
- **Context compaction** — four-layer strategy (budget → snip → micro → LLM summarise)

## Project structure

```
ds-agent/
├── main.py                    # CLI entry point
├── pyproject.toml
├── .env                       # DEEPSEEK_API_KEY=sk-xxx
│
├── skills/                    # Skill playbooks (optional)
│   └── <name>/
│       └── SKILL.md
│
└── agent/
    ├── config.py              # Constants, env vars, OpenAI client, shared state
    ├── utils.py               # terminal_print, safe_path, has_tool_use, extract_text
    │
    ├── core/                  # Agent loop & supporting infrastructure
    │   ├── loop.py            # Main execution cycle
    │   ├── prompt.py          # System prompt assembly
    │   ├── context.py         # Memory / context state
    │   ├── compaction.py      # Four-layer context compaction
    │   └── recovery.py        # Retry, model fallback, error detection
    │
    ├── tools/                 # Tool definitions and handlers
    │   ├── registry.py        # BUILTIN_TOOLS + BUILTIN_HANDLERS + assemble_tool_pool
    │   ├── bash.py            # Shell command execution
    │   ├── file.py            # read_file / write_file / edit_file / glob
    │   ├── todo.py            # Session todo list
    │   ├── skill.py           # Skill scanning / loading
    │   ├── subagent.py        # Short-lived focused subagent
    │   └── mcp.py             # MCP client + mock servers (docs, deploy)
    │
    ├── systems/               # Durable subsystems
    │   ├── tasks.py           # Task CRUD, dependencies, claim / complete
    │   ├── worktree.py        # Git worktree create / remove / keep
    │   ├── cron.py            # 5-field cron scheduler with durable persistence
    │   └── background.py      # Async background task runner
    │
    ├── teams/                 # Multi-agent collaboration
    │   ├── bus.py             # JSONL message bus
    │   ├── protocol.py        # Request/response state machine (shutdown, plan approval)
    │   ├── teammate.py        # Autonomous teammate thread
    │   └── autonomous.py      # Idle polling for unclaimed tasks
    │
    └── hooks/                 # Tool-call interceptor pipeline
        ├── __init__.py        # HOOKS pipeline + register / trigger
        ├── permission.py      # Deny-list, destructive confirmation, path containment
        └── logging.py         # Diagnostic hooks (registered on import)
```

## Quick start

### 1. Install dependencies

```bash
uv sync
```

### 2. Set your API key

Create a `.env` file in the project root:

```env
DEEPSEEK_API_KEY=sk-your-key-here
```

Optional overrides:

```env
MODEL_ID=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
FALLBACK_MODEL_ID=deepseek-chat   # used after consecutive 529 errors
```

### 3. Run

```bash
uv run python main.py
```

```
ds-agent: comprehensive coding agent (DeepSeek)
Enter a question, press Enter to send. Type q to quit.

s20 >> Create a task to write a README
```

Type `q`, `exit`, or an empty line to quit.

## Adding skills

Create a folder under `skills/` with a `SKILL.md` file:

```
skills/
└── my-skill/
    └── SKILL.md
```

`SKILL.md` uses YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does
---

# Instructions

Step-by-step guidance for the agent…
```

The agent discovers skills automatically and loads them via the `load_skill` tool.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | **Required.** DeepSeek API key |
| `MODEL_ID` | `deepseek-chat` | Model name |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API base URL |
| `FALLBACK_MODEL_ID` | — | Fallback model on 529 overload |

## API compatibility

Although the tool schemas use `input_schema` naming (carried over from the original codebase), all actual API calls use the **OpenAI chat completions format**:

- `client.chat.completions.create(...)` with `tools` as `[{type: "function", function: {...}}]`
- `tool_calls` on the assistant message
- Role `tool` messages for results
- System prompt as `role: "system"`

This means any OpenAI-compatible provider (DeepSeek, OpenAI, local vLLM, etc.) works by changing `DEEPSEEK_BASE_URL` and `MODEL_ID`.
