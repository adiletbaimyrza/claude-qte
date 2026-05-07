"""Shared low-level helpers used across multiple modules."""

import os
import subprocess
import sys
import tempfile
import threading
import time

TMP_DIR = os.path.join(tempfile.gettempdir(), "claude-qte")
ANSWER_TIMEOUT = 300  # seconds the gate may sit on the popup

_request_lock = threading.Lock()
_request_seq = 0


def next_request_id() -> str:
    """Monotonic id used to pair a question file with its answer file."""
    global _request_seq
    with _request_lock:
        _request_seq += 1
        return f"{int(time.time())}-{_request_seq}-{os.getpid()}"


def current_invocation() -> list:
    """argv-shaped command that re-launches this program."""
    if getattr(sys, "frozen", False):
        # PyInstaller-bundled binary
        return [sys.executable]
    # Running from source — re-invoke the package with the same interpreter.
    return [sys.executable, "-m", "claude_qte"]


def shell_quote(s: str) -> str:
    """Quote a string for /bin/sh."""
    if not s:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def applescript_string(s: str) -> str:
    """Quote a string for AppleScript."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def osascript(script: str, *, capture: bool = False, timeout: float = None):
    """Run an AppleScript snippet via osascript. Returns a CompletedProcess."""
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=capture,
        text=True,
        check=False,
        timeout=timeout,
    )
