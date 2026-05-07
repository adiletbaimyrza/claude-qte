"""Claude Code ``PreToolUse`` hook entry point.

Reads the JSON event on stdin, decides whether to defer to the native
inline prompt or to call the popup gate, and emits the hook decision JSON.
"""

import json
import os
import subprocess
import sys

from claude_qte._platform import frontmost_terminal_tty, idle_seconds
from claude_qte._runtime import ANSWER_TIMEOUT, TMP_DIR, pick_free_port, wait_for_port

# How long the user can be away from the keyboard / off the terminal before
# we assume they aren't watching and pop up the QTE window.
USER_PRESENCE_IDLE_SECONDS = 20


def run_hook() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit_decision("ask")
        return

    ppid = os.getppid()
    port = _ensure_gate(ppid)

    # The user may instruct Claude (via CLAUDE.md) to curl the gate before
    # each action. Installing claude-qte already implies consent for that
    # self-call, so auto-allow it — the *actual* command will hit the hook
    # again and get prompted there.
    if port and is_gate_self_call(event, port):
        emit_decision("allow", "claude-qte gate self-call")
        return

    if user_is_present():
        emit_decision("ask")
        return

    if port is None:
        # Gate unavailable — fail safe to native flow.
        emit_decision("ask")
        return

    question = describe_tool(event.get("tool_name", ""), event.get("tool_input", {}))
    answer = call_gate(port, question)

    if answer is None:
        emit_decision("ask")
        return

    if answer.get("approved"):
        emit_decision("allow", answer.get("answer") or "approved via claude-qte")
    else:
        emit_decision("deny", answer.get("answer") or "denied via claude-qte")


def _gate_port_file(ppid: int) -> str:
    return os.path.join(TMP_DIR, f"gate-{ppid}.port")


def _ping_gate(port: int) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _spawn_gate(port: int, ppid: int) -> bool:
    """Spawn the gate on *port* and wait up to 5 s for it to come up."""
    from claude_qte._runtime import current_invocation

    binary = current_invocation()
    try:
        subprocess.Popen(
            [*binary, "--port", str(port), "--parent-pid", str(ppid), "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError):
        return False

    if not wait_for_port(port, timeout=5.0):
        return False

    port_file = _gate_port_file(ppid)
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        with open(port_file, "w") as fh:
            fh.write(str(port))
    except OSError:
        pass
    return True


def _ensure_gate(ppid: int) -> int | None:
    """Return a live gate port for *ppid*, lazily spawning one if needed."""
    # Fast path: env var set by the wrapper.
    env_val = os.environ.get("CLAUDE_QTE_PORT", "")
    if env_val.isdigit():
        port = int(env_val)
        if _ping_gate(port):
            return port

    # Second path: port file written by wrapper or a prior lazy-spawn.
    port_file = _gate_port_file(ppid)
    try:
        with open(port_file) as fh:
            raw = fh.read().strip()
        if raw.isdigit():
            port = int(raw)
            if _ping_gate(port):
                return port
    except OSError:
        pass

    # Lazy spawn: no running gate found — start one now.
    port = pick_free_port()
    if _spawn_gate(port, ppid):
        return port
    return None


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
