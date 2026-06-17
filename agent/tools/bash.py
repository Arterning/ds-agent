"""
Shell command execution.
"""

import subprocess
from pathlib import Path

from agent.config import WORKDIR


def run_bash(command: str, cwd: Path | None = None,
             run_in_background: bool = False) -> str:
    """Execute *command* in a subprocess.  *run_in_background* is consumed by
    the dispatcher; direct execution ignores it."""
    try:
        r = subprocess.run(
            command, shell=True,
            cwd=cwd or WORKDIR,
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
