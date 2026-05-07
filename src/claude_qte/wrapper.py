"""``claude-qte run <cmd>...`` — per-session wrapper.

Picks a free port, spawns the gate as a detached child, sets
``CLAUDE_QTE_PORT`` so the hook calls the right gate, runs the command,
and tears the gate down on exit.
"""

import contextlib
import os
import platform
import signal
import socket
import subprocess
import sys
import time

from claude_qte._runtime import current_invocation


def run_command(argv: list) -> None:
    """Spawn a per-session gate, exec ``argv``, kill the gate on exit."""
    if not argv:
        sys.stderr.write("Usage: claude-qte run <command> [args...]\n")
        sys.exit(2)
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte currently supports macOS only.\n")
        sys.exit(2)

    port = pick_free_port()
    binary = current_invocation()
    gate_proc = subprocess.Popen(
        [*binary, "--port", str(port), "--parent-pid", str(os.getpid()), "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Own process group, so SIGINT to the foreground group (ctrl-c
        # hitting `claude`) doesn't also kill the gate.
        start_new_session=True,
    )

    if not wait_for_port(port, timeout=5.0):
        with contextlib.suppress(OSError):
            gate_proc.terminate()
        sys.stderr.write(f"claude-qte: gate did not start on port {port}\n")
        sys.exit(1)

    def _cleanup_gate():
        if gate_proc.poll() is None:
            try:
                gate_proc.terminate()
                gate_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                gate_proc.kill()
            except OSError:
                pass

    def _on_signal(signum, _frame):
        _cleanup_gate()
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGHUP, _on_signal)
    # Let SIGINT pass through to the child (claude handles ctrl-c itself).
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    env = os.environ.copy()
    env["CLAUDE_QTE_PORT"] = str(port)

    try:
        proc = subprocess.run(argv, env=env)
        rc = proc.returncode
    finally:
        _cleanup_gate()

    sys.exit(rc)


def pick_free_port() -> int:
    """Bind ``:0`` and return whatever port the OS hands back. Brief race
    window between release and the gate's bind — fine for a local dev tool."""
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
