"""Shared low-level helpers used across multiple modules."""

import contextlib
import os
import socket
import sys
import tempfile
import threading
import time

TMP_DIR = os.path.join(tempfile.gettempdir(), "claude-qte")
ANSWER_TIMEOUT = 300  # seconds the gate may sit on the popup

DISABLED_FLAG = os.path.expanduser("~/.config/claude-qte/disabled")

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


def safe_unlink(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


def pick_free_port() -> int:
    """Bind ``:0`` and return the OS-assigned port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    return False
