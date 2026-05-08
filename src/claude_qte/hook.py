"""Claude Code ``PreToolUse`` hook entry point.

Reads the JSON event on stdin, decides whether to defer to the native
inline prompt or to call the popup gate, and emits the hook decision JSON.
"""

import json
import os
import subprocess
import sys

from claude_qte._platform import frontmost_terminal_tty, idle_seconds
from claude_qte._runtime import (
    ANSWER_TIMEOUT,
    DISABLED_FLAG,
    TMP_DIR,
    pick_free_port,
    wait_for_port,
)
from claude_qte.denial_log import log_denial

# How long the user can be away from the keyboard / off the terminal before
# we assume they aren't watching and pop up the QTE window.
USER_PRESENCE_IDLE_SECONDS: float = float(os.environ.get("CLAUDE_QTE_IDLE_SECONDS", "20"))


def run_hook() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit_decision("ask")
        return

    if os.path.exists(DISABLED_FLAG):
        emit_decision("ask")
        return

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    cwd = event.get("cwd", "")

    if not tool_name:
        emit_decision("ask")
        return

    # If the tool call matches a permissions.allow rule in Claude's settings,
    # skip the popup — the user has already pre-approved it.
    if _is_permitted(tool_name, tool_input, cwd):
        emit_decision("allow", "matches permissions.allow rule")
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

    question = describe_tool(tool_name, tool_input)
    answer = call_gate(port, question)

    if answer is None:
        emit_decision("ask")
        return

    if answer.get("approved"):
        emit_decision("allow", answer.get("answer") or "approved via claude-qte")
    else:
        denial_reason = answer.get("answer") or "denied via claude-qte"
        log_denial(tool_name, tool_input, denial_reason, cwd)
        emit_decision("deny", denial_reason)


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
    if not front_tty:
        # TTY detection unavailable (xdotool missing or Wayland): trust idle time alone.
        return True
    return parent_tty == front_tty


def _parent_tty() -> str:
    # Walk up the process tree until we find a process with a real TTY.
    # The hook's immediate parent (Claude Code's hook runner) often has no TTY
    # (shows "?"), but Claude Code itself and the shell above it do.
    pid = os.getppid()
    seen: set[int] = set()
    while pid and pid not in seen:
        seen.add(pid)
        try:
            out = subprocess.run(
                ["ps", "-o", "tty=,ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return ""
        if not out:
            return ""
        parts = out.split()
        tty = parts[0] if parts else "?"
        ppid_str = parts[1] if len(parts) > 1 else "0"
        if tty and tty != "?":
            return tty if tty.startswith("/dev/") else f"/dev/{tty}"
        try:
            pid = int(ppid_str)
        except ValueError:
            return ""
        if pid <= 1:
            return ""
    return ""


def _load_allow_rules(cwd: str) -> list[str]:
    """Return the merged permissions.allow list from user + project settings."""
    rules: list[str] = []
    candidates = [os.path.expanduser("~/.claude/settings.json")]
    # Walk up from cwd looking for .claude/settings.json
    path = os.path.abspath(cwd) if cwd else ""
    while path and path != os.path.dirname(path):
        candidate = os.path.join(path, ".claude", "settings.json")
        if os.path.exists(candidate):
            candidates.append(candidate)
            break
        path = os.path.dirname(path)

    for settings_path in candidates:
        try:
            with open(settings_path, encoding="utf-8") as fh:
                data = json.load(fh)
            rules.extend(data.get("permissions", {}).get("allow", []))
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return rules


def _matches_rule(rule: str, tool_name: str, tool_input: dict) -> bool:
    """Return True if *tool_name* / *tool_input* matches a permission rule string.

    Rule format (same as Claude Code's permissions.allow):
      "Bash"            → matches all Bash calls
      "Bash(git *)"     → Bash where command glob-matches "git *"
      "Edit"            → matches all Edit calls
      "Edit(/path/*)"   → Edit where file_path glob-matches "/path/*"
      "Write(/path/*)"  → Write where file_path glob-matches "/path/*"
    """
    import fnmatch

    rule = rule.strip()
    if "(" in rule:
        rule_tool, rest = rule.split("(", 1)
        rule_tool = rule_tool.strip()
        pattern = rest.rstrip(")").strip()
    else:
        rule_tool = rule
        pattern = None

    if rule_tool != tool_name:
        return False
    if pattern is None or pattern == "*":
        return True

    # Pick the right field to match against per tool.
    if tool_name == "Bash":
        subject = (tool_input.get("command") or "").strip()
    elif tool_name in ("Edit", "Write", "NotebookEdit"):
        subject = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    else:
        subject = json.dumps(tool_input, ensure_ascii=False)

    return fnmatch.fnmatch(subject, pattern)


def _is_permitted(tool_name: str, tool_input: dict, cwd: str) -> bool:
    """True if the tool call is pre-approved via permissions.allow in settings."""
    rules = _load_allow_rules(cwd)
    return any(_matches_rule(rule, tool_name, tool_input) for rule in rules)


def describe_tool(tool_name: str, tool_input: dict) -> str:
    """Render a tool-use event as a human-readable question for the popup.

    For Write/Edit tools, returns a JSON-encoded diff payload so the TUI can
    render colored unified-diff output. All other tools return plain text.
    """
    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "").strip()
        desc = (tool_input.get("description") or "").strip()
        return f"Bash — {desc}\n\n$ {cmd}" if desc else f"Bash\n\n$ {cmd}"
    if tool_name == "Edit":
        path = tool_input.get("file_path", "")
        diff = _edit_diff(path, tool_input.get("old_string", ""), tool_input.get("new_string", ""))
        return json.dumps({"__diff__": True, "path": path, "diff": diff})
    if tool_name == "Write":
        path = tool_input.get("file_path", "")
        new_content = tool_input.get("content") or ""
        diff = _write_diff(path, new_content)
        return json.dumps({"__diff__": True, "path": path, "diff": diff})
    if tool_name == "NotebookEdit":
        path = tool_input.get("notebook_path") or tool_input.get("file_path", "")
        return f"NotebookEdit {path}"
    detail = json.dumps(tool_input, ensure_ascii=False)
    if len(detail) > 800:
        detail = detail[:800] + "…"
    return f"{tool_name}\n\n{detail}"


def _edit_diff(path: str, old: str, new: str) -> str:
    import difflib

    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    chunks = list(
        difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm="")
    )
    if not chunks:
        return f"(no changes to {path})"
    return "".join(chunks)


def _write_diff(path: str, new_content: str) -> str:
    import difflib

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            old_lines = fh.readlines()
    except FileNotFoundError:
        old_lines = []

    new_lines = new_content.splitlines(keepends=True)
    fromfile = path if old_lines else "/dev/null"
    chunks = list(
        difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=path, lineterm="")
    )
    if not chunks:
        return f"(no changes to {path})"
    return "".join(chunks)


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
