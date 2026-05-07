"""``claude-qte run <cmd>...`` — per-session wrapper.

Picks a free port, spawns the gate as a detached child, sets
``CLAUDE_QTE_PORT`` so the hook calls the right gate, runs the command,
and tears the gate down on exit.
"""

import contextlib
import os
import signal
import subprocess
import sys

from claude_qte._runtime import TMP_DIR, current_invocation, pick_free_port, wait_for_port


def run_command(argv: list) -> None:
    """Spawn a per-session gate, exec ``argv``, kill the gate on exit."""
    if not argv:
        sys.stderr.write("Usage: claude-qte run <command> [args...]\n")
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

    # Write port file so hook.py can discover the gate without the env var.
    os.makedirs(TMP_DIR, exist_ok=True)
    port_file = os.path.join(TMP_DIR, f"gate-{os.getpid()}.port")
    with contextlib.suppress(OSError), open(port_file, "w") as fh:
        fh.write(str(port))

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
