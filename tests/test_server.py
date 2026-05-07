"""Tests for claude_qte.server — HTTP handler logic, no real sockets."""

import json
from http.server import HTTPServer
from io import BytesIO
from unittest.mock import MagicMock, patch


def _make_handler(path, method="POST", body=b"", headers=None):
    """Build an ApprovalHandler instance wired to fake socket objects."""
    from claude_qte.server import ApprovalHandler

    client_address = ("127.0.0.1", 12345)
    server = MagicMock(spec=HTTPServer)
    server.server_port = 9999

    handler = ApprovalHandler.__new__(ApprovalHandler)
    handler.server = server
    handler.client_address = client_address
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = method
    handler.path = path
    handler.headers = {"Content-Length": str(len(body)), **(headers or {})}
    handler.rfile = BytesIO(body)

    response_buf = BytesIO()
    handler.wfile = response_buf
    handler._headers_buffer = []
    handler._response_buf = response_buf

    # Capture send_response / send_header / end_headers / wfile.write
    written = {"code": None, "headers": [], "body": b""}

    def _send_response(code, message=None):
        written["code"] = code

    def _send_header(k, v):
        written["headers"].append((k, v))

    def _end_headers():
        pass

    def _write(data):
        written["body"] += data

    handler.send_response = _send_response
    handler.send_header = _send_header
    handler.end_headers = _end_headers
    handler.wfile = MagicMock()
    handler.wfile.write = _write

    return handler, written


class TestApprovalHandlerPing:
    def test_get_ping_returns_ok(self):
        handler, written = _make_handler("/ping", method="GET")
        handler.do_GET()
        assert written["code"] == 200
        data = json.loads(written["body"])
        assert data["status"] == "ok"
        assert data["port"] == 9999

    def test_get_unknown_path_returns_404(self):
        handler, written = _make_handler("/nope", method="GET")
        handler.do_GET()
        assert written["code"] == 404

    def test_get_ask_missing_question_returns_400(self):
        handler, written = _make_handler("/ask?q=", method="GET")
        handler.do_GET()
        assert written["code"] == 400


class TestApprovalHandlerAsk:
    def test_post_ask_approved(self):
        body = json.dumps({"q": "Do X?"}).encode()
        handler, written = _make_handler("/ask", body=body)
        with patch("claude_qte.server.prompt_user", return_value={"approved": True, "text": "yes"}):
            handler.do_POST()
        assert written["code"] == 200
        data = json.loads(written["body"])
        assert data["approved"] is True
        assert data["answer"] == "yes"

    def test_post_ask_denied(self):
        body = json.dumps({"q": "Do X?"}).encode()
        handler, written = _make_handler("/ask", body=body)
        with patch("claude_qte.server.prompt_user", return_value={"approved": False, "text": "no"}):
            handler.do_POST()
        assert written["code"] == 200
        data = json.loads(written["body"])
        assert data["approved"] is False

    def test_post_ask_empty_body_returns_400(self):
        handler, written = _make_handler("/ask", body=b"")
        handler.do_POST()
        assert written["code"] == 400

    def test_post_unknown_path_returns_404(self):
        handler, written = _make_handler("/other", body=b"x")
        handler.do_POST()
        assert written["code"] == 404

    def test_post_ask_prompt_user_exception_returns_500(self):
        body = json.dumps({"q": "Do X?"}).encode()
        handler, written = _make_handler("/ask", body=body)
        with patch("claude_qte.server.prompt_user", side_effect=RuntimeError("boom")):
            handler.do_POST()
        assert written["code"] == 500
        data = json.loads(written["body"])
        assert data["approved"] is False

    def test_post_ask_urlencoded_body(self):
        body = b"q=Do+something%3F"
        handler, written = _make_handler("/ask", body=body)
        with patch("claude_qte.server.prompt_user", return_value={"approved": True, "text": "ok"}):
            handler.do_POST()
        assert written["code"] == 200

    def test_post_ask_question_field_alias(self):
        body = json.dumps({"question": "Is this ok?"}).encode()
        handler, written = _make_handler("/ask", body=body)
        with patch("claude_qte.server.prompt_user", return_value={"approved": True, "text": "yes"}):
            handler.do_POST()
        assert written["code"] == 200

    def test_get_ask_with_question(self):
        from urllib.parse import quote

        q = quote("Shall I?")
        handler, written = _make_handler(f"/ask?q={q}", method="GET")
        with patch("claude_qte.server.prompt_user", return_value={"approved": True, "text": "yes"}):
            handler.do_GET()
        assert written["code"] == 200


class TestLogMessage:
    def test_log_message_is_silent(self):
        from claude_qte.server import ApprovalHandler

        handler = ApprovalHandler.__new__(ApprovalHandler)
        handler.log_message("%s", "test")  # must not raise or print


class TestWatchParent:
    def test_exits_when_parent_gone(self, monkeypatch):

        import claude_qte.server as server_mod
        from claude_qte.server import _watch_parent

        exited = []

        class _Exited(Exception):
            pass

        def _kill(pid, sig):
            raise ProcessLookupError

        def _exit(code):
            exited.append(code)
            raise _Exited

        monkeypatch.setattr(server_mod.os, "kill", _kill)
        monkeypatch.setattr(server_mod.os, "_exit", _exit)
        monkeypatch.setattr(server_mod.time, "sleep", lambda _: None)

        try:
            _watch_parent(9999)
        except _Exited:
            pass
        assert exited == [0]


class TestRunServer:
    def test_run_server_serves_and_shuts_down_on_keyboard_interrupt(self, monkeypatch):
        from claude_qte.server import run_server

        mock_httpd = MagicMock()
        mock_httpd.serve_forever.side_effect = KeyboardInterrupt

        with patch("claude_qte.server.HTTPServer", return_value=mock_httpd):
            run_server(9998, quiet=True)

        mock_httpd.server_close.assert_called_once()

    def test_run_server_starts_parent_watcher_when_pid_given(self, monkeypatch):
        from claude_qte.server import run_server

        mock_httpd = MagicMock()
        mock_httpd.serve_forever.side_effect = KeyboardInterrupt

        threads_started = []

        class _FakeThread:
            def __init__(self, target, args=(), daemon=False):
                threads_started.append(target.__name__)

            def start(self):
                pass

        with (
            patch("claude_qte.server.HTTPServer", return_value=mock_httpd),
            patch("claude_qte.server.threading.Thread", _FakeThread),
        ):
            run_server(9997, parent_pid=1234, quiet=True)

        assert "_watch_parent" in threads_started
