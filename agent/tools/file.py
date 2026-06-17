"""
File tools — read, write, edit, glob.  All enforce workspace containment
via safe_path.
"""

import glob as _glob
from pathlib import Path

from agent.utils import safe_path


def run_read(path: str, limit: int | None = None,
             offset: int = 0, cwd: Path | None = None) -> str:
    try:
        lines = safe_path(path, cwd).read_text().splitlines()
        offset = max(int(offset or 0), 0)
        limit_val = int(limit) if limit is not None else None
        lines = lines[offset:]
        if limit_val is not None and limit_val < len(lines):
            lines = lines[:limit_val] + [f"... ({len(lines) - limit_val} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str, cwd: Path | None = None) -> str:
    try:
        fp = safe_path(path, cwd)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str,
             cwd: Path | None = None) -> str:
    try:
        fp = safe_path(path, cwd)
        text = fp.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str, cwd: Path | None = None) -> str:
    try:
        from agent.config import WORKDIR
        base_path = cwd or WORKDIR
        results = []
        for match in _glob.glob(pattern, root_dir=base_path):
            if (base_path / match).resolve().is_relative_to(base_path):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"
