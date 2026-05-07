"""Read/write helpers for ``~/.claude/settings.json``.

Pure-ish: only touches the filesystem, no global side effects beyond the
settings file itself. Easy to unit-test by pointing ``SETTINGS_PATH`` at a
tmp file.
"""

import json
import os

SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")

# We identify our hook entry by looking for this substring inside the
# `command` string, so we don't have to add fields Claude Code might reject.
HOOK_COMMAND_MARKER = "claude-qte hook"

# Tools we want the hook to fire on.
HOOK_MATCHER = "Bash|Edit|Write|NotebookEdit"
HOOK_TIMEOUT_SECONDS = 600


def load_settings(path: str = SETTINGS_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict, path: str = SETTINGS_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def patch_for_hook(bin_path: str, path: str = SETTINGS_PATH) -> None:
    """Idempotently install the PreToolUse hook entry pointing at ``bin_path``."""
    settings = load_settings(path)
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])

    new_entry = {
        "matcher": HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": f"{bin_path} hook",
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
        ],
    }

    rewritten = False
    for i, group in enumerate(pre):
        for cmd in group.get("hooks") or []:
            if HOOK_COMMAND_MARKER in (cmd.get("command") or ""):
                pre[i] = new_entry
                rewritten = True
                break
        if rewritten:
            break
    if not rewritten:
        pre.append(new_entry)

    save_settings(settings, path)


def unpatch_hook(path: str = SETTINGS_PATH) -> bool:
    """Remove the claude-qte hook entry. Returns True if anything was removed."""
    if not os.path.exists(path):
        return False
    settings = load_settings(path)
    hooks = settings.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    cleaned = [
        group for group in pre
        if not any(
            HOOK_COMMAND_MARKER in (cmd.get("command") or "")
            for cmd in (group.get("hooks") or [])
        )
    ]
    if cleaned == pre:
        return False
    if cleaned:
        hooks["PreToolUse"] = cleaned
    else:
        hooks.pop("PreToolUse", None)
    if not hooks:
        settings.pop("hooks", None)
    save_settings(settings, path)
    return True
