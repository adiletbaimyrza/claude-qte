"""Append-only denial log written whenever the gate denies a tool call.

Each line is a JSON object (JSONL) so the file is both human-readable and
machine-parseable.  The log lives at ``~/.claude/denials.log`` — the same
directory as Claude Code's own config, so it's easy to find.
"""

import json
import os
import time

DENIAL_LOG_PATH = os.path.expanduser("~/.claude/denials.log")


def log_denial(
    tool_name: str,
    tool_input: dict,
    reason: str,
    cwd: str = "",
    path: str = DENIAL_LOG_PATH,
) -> None:
    """Append one denial entry to *path* (default: ``~/.claude/denials.log``)."""
    entry = {
        "ts": int(time.time()),
        "tool": tool_name,
        "reason": reason,
    }
    if cwd:
        entry["cwd"] = cwd
    # Include the most useful fields per tool without dumping full input.
    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "").strip()
        if cmd:
            entry["command"] = cmd
    elif tool_name in ("Edit", "Write"):
        fp = tool_input.get("file_path") or ""
        if fp:
            entry["file_path"] = fp
    elif tool_name == "NotebookEdit":
        fp = tool_input.get("notebook_path") or tool_input.get("file_path") or ""
        if fp:
            entry["file_path"] = fp

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Never let logging break the hook decision


def print_denials(path: str = DENIAL_LOG_PATH, last: int = 0) -> None:
    """Pretty-print the denial log to stdout.

    Args:
        path: Path to the JSONL denial log.
        last: If > 0, show only the last *n* entries.
    """
    import datetime

    if not os.path.exists(path):
        print("  No denials logged yet.")
        return

    try:
        with open(path, encoding="utf-8") as fh:
            lines = [line.rstrip("\n") for line in fh if line.strip()]
    except OSError as exc:
        print(f"  Could not read {path}: {exc}")
        return

    if not lines:
        print("  No denials logged yet.")
        return

    if last > 0:
        lines = lines[-last:]

    print(f"  {'TIME':<20} {'TOOL':<16} {'DETAIL':<40} REASON")
    print("  " + "-" * 100)
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("ts", 0)
        dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
        tool = entry.get("tool", "?")
        reason = entry.get("reason", "")
        detail = entry.get("command") or entry.get("file_path") or ""
        if len(detail) > 40:
            detail = detail[:37] + "..."
        print(f"  {dt:<20} {tool:<16} {detail:<40} {reason}")
