"""
Hook pipeline — event → callback chain.

Events: UserPromptSubmit, PreToolUse, PostToolUse, Stop.
Callbacks return None to allow, or a string to block (for PreToolUse).
"""

HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None
