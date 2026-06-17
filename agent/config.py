"""
Agent configuration — constants, environment, paths.

All modules import shared state from here so there is one source of truth
for the workspace root, API client, model, and directory layout.
"""

import os, re, threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# ── Workspace ────────────────────────────────────────────────────────────────

WORKDIR = Path.cwd()

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TASKS_DIR = WORKDIR / ".tasks"
WORKTREES_DIR = WORKDIR / ".worktrees"
MAILBOX_DIR = WORKDIR / ".mailboxes"
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
DURABLE_CRON_PATH = WORKDIR / ".scheduled_tasks.json"

TASKS_DIR.mkdir(exist_ok=True)
WORKTREES_DIR.mkdir(exist_ok=True)
MAILBOX_DIR.mkdir(exist_ok=True)

# ── OpenAI / DeepSeek client ────────────────────────────────────────────────

from openai import OpenAI

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

client = OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
MODEL = os.getenv("MODEL_ID", "deepseek-chat")
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# ── Tuning knobs ────────────────────────────────────────────────────────────

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50_000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30_000
IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36ms20 >> \033[0m"
CLI_ACTIVE = False

# ── Readline ────────────────────────────────────────────────────────────────

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

# ── Globally shared mutable state (kept minimal) ────────────────────────────

CURRENT_TODOS: list[dict] = []
active_teammates: dict[str, bool] = {}
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()
_bg_counter = 0

# MCP
mcp_clients: dict[str, "MCPClient"] = {}

# Reusable regex
VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')
