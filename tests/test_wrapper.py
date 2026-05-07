"""Networking helpers in :mod:`claude_qte.wrapper`."""

import socket
import threading

import pytest

from claude_qte.wrapper import pick_free_port, wait_for_port


class TestPickFreePort:
    def test_returns_bindable_port(self):
        port = pick_free_port()
        assert 1024 <= port <= 65535
        # Port should still be free immediately after — bind to confirm.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))

    def test_distinct_ports_on_consecutive_calls(self):
        # Not strictly guaranteed, but the OS basically never hands the same
        # ephemeral port back-to-back.
        ports = {pick_free_port() for _ in range(5)}
        assert len(ports) > 1


class TestWaitForPort:
    def test_returns_false_for_unbound_port(self):
        port = pick_free_port()
        assert wait_for_port(port, timeout=0.3) is False

    def test_returns_true_when_listener_is_up(self):
        port = pick_free_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)

        # Accept-and-discard on a thread so the connect from wait_for_port
        # actually succeeds.
        def serve_one():
            try:
                conn, _ = sock.accept()
                conn.close()
            except OSError:
                pass

        t = threading.Thread(target=serve_one, daemon=True)
        t.start()
        try:
            assert wait_for_port(port, timeout=2.0) is True
        finally:
            sock.close()
            t.join(timeout=1.0)
