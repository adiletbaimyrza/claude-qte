"""HTTP gate that exposes ``/ask`` and ``/ping``.

A POST or GET to ``/ask`` blocks until the popup returns; ``/ping`` is
cheap and used to detect that the gate is up.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote_plus, urlparse

from claude_qte import __version__
from claude_qte._runtime import TMP_DIR
from claude_qte.popup import prompt_user


class ApprovalHandler(BaseHTTPRequestHandler):
    server_version = f"claude-qte/{__version__}"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            self._json({"status": "ok", "port": self.server.server_port})
            return
        if parsed.path != "/ask":
            self._json({"error": "POST /ask {q:...} or GET /ask?q=..."}, 404)
            return
        params = parse_qs(parsed.query)
        question = unquote_plus(params.get("q", [""])[0]).strip()
        self._handle_ask(question)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/ask":
            self._json({"error": "POST /ask {q:...}"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        question = ""
        if raw:
            try:
                payload = json.loads(raw)
                question = str(payload.get("q") or payload.get("question") or "").strip()
            except json.JSONDecodeError:
                params = parse_qs(raw)
                question = unquote_plus(params.get("q", [""])[0]).strip()
        self._handle_ask(question)

    def _handle_ask(self, question: str):
        if not question:
            self._json({"error": "Missing question (JSON {q:...} or ?q=...)"}, 400)
            return
        try:
            answer = prompt_user(question)
        except Exception as exc:
            self._json({"approved": False, "answer": f"error: {exc}", "message": str(exc)}, 500)
            return
        self._json(
            {
                "approved": answer["approved"],
                "answer": answer["text"],
                "message": answer["text"],
            }
        )

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int, parent_pid: int = 0, quiet: bool = False) -> None:
    os.makedirs(TMP_DIR, exist_ok=True)

    # If launched with --parent-pid (e.g. from `claude-qte run`), exit as soon
    # as that process is gone — covers SIGKILL of the wrapper and other
    # cases where the cleanup trap can't run.
    if parent_pid:
        threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()

    httpd = HTTPServer(("127.0.0.1", port), ApprovalHandler)
    if not quiet:
        print(f"""
  claude-qte — running on http://localhost:{port}

  Wire it into Claude Code by adding to ~/.claude/CLAUDE.md:
      Before any tool use, run:
        curl -s -X POST http://localhost:{port}/ask \\
             -H "Content-Type: application/json" \\
             -d "$(jq -nc --arg q '<full description>' '{{q:$q}}')"
      Wait for the JSON response. Proceed only if "approved" is true.

  Ctrl+C to quit.
""")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        if not quiet:
            print("\nShutting down.")
        httpd.server_close()


def _watch_parent(pid: int) -> None:
    """Exit the gate as soon as the wrapper process disappears."""
    while True:
        time.sleep(2)
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            os._exit(0)
