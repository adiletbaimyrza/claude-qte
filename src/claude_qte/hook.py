"""Claude Code ``PreToolUse`` hook entry point.

Reads the JSON event on stdin, decides whether to defer to the native
inline prompt or to call the popup gate, and emits the hook decision JSON.
"""

import json
import os
import subprocess
import sys

from claude_qte._platform import frontmost_terminal_tty, idle_seconds
from claude_qte._runtime import ANSWER_TIMEOUT

# How long the user can be away from the keyboard / off the terminal before
# we assume they aren't watching and pop up the QTE window.
USER_PRESENCE_IDLE_SECONDS = 20


def run_hook(port: int) -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # Malformed input — fail safe to native flow.
        emit_decision("ask")
        return

    # The user may instruct Claude (via CLAUDE.md) to curl the gate before
    # each action. Installing claude-qte already implies consent for that
    # self-call, so auto-allow it — the *actual* command will hit the hook
    # again and get prompted there.
    if is_gate_self_call(event, port):
        emit_decision("allow", "claude-qte gate self-call")
        return

    if user_is_present():
        emit_decision("ask")
        return

    question = describe_tool(event.get("tool_name", ""), event.get("tool_input", {}))
    answer = call_gate(port, question)

    if answer is None:
        # Gate unreachable — fail safe to native flow so Claude Code keeps
        # working even if the user hasn't started the gate yet.
        emit_decision("ask")
        return

    if answer.get("approved"):
        emit_decision("allow", answer.get("answer") or "approved via claude-qte")
    else:
        emit_decision("deny", answer.get("answer") or "denied via claude-qte")


def is_gate_self_call(event: dict, port: int) -> bool:
    if event.get("tool_name") != "Bash":
        return False
    cmd = (event.get("tool_input") or {}).get("command") or ""
    for host in ("localhost", "127.0.0.1"):
        for path in ("/ask", "/ping"):
            if f"{host}:{port}{path}" in cmd:
                return True
    return False


def emit_decision(decision: str, reason: str = "") -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def user_is_present() -> bool:
    """True iff the user is at the keyboard AND looking at the terminal where
    Claude Code is running."""
    if idle_seconds() > USER_PRESENCE_IDLE_SECONDS:
        return False
    parent_tty = _parent_tty()
    if not parent_tty:
        return False
    front_tty = frontmost_terminal_tty()
    return bool(front_tty) and parent_tty == front_tty


def _parent_tty() -> str:
    try:
        ppid = os.getppid()
        out = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(ppid)],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    if not out or out == "?":
        return ""
    return out if out.startswith("/dev/") else f"/dev/{out}"


def describe_tool(tool_name: str, tool_input: dict) -> str:
    """Render a tool-use event as a human-readable question for the popup."""
    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "").strip()
        desc = (tool_input.get("description") or "").strip()
        return f"Bash — {desc}\n\n$ {cmd}" if desc else f"Bash\n\n$ {cmd}"
    if tool_name == "Edit":
        path = tool_input.get("file_path", "")
        return f"Edit {path}"
    if tool_name == "Write":
        path = tool_input.get("file_path", "")
        size = len(tool_input.get("content") or "")
        return f"Write {path} ({size} chars)"
    if tool_name == "NotebookEdit":
        path = tool_input.get("notebook_path") or tool_input.get("file_path", "")
        return f"NotebookEdit {path}"
    detail = json.dumps(tool_input, ensure_ascii=False)
    if len(detail) > 800:
        detail = detail[:800] + "…"
    return f"{tool_name}\n\n{detail}"


def call_gate(port: int, question: str):
    import urllib.error
    import urllib.request

    payload = json.dumps({"q": question}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Long timeout: gate may sit on the popup for a while.
        with urllib.request.urlopen(req, timeout=ANSWER_TIMEOUT + 30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
