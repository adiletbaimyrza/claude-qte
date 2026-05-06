#!/usr/bin/env python3
"""
claude-qte — Quick-Time Event for Claude Code

A local approval gate that mirrors Claude Code's permission UX. Run it once
and leave it in the background. When Claude is about to use a tool, it calls:

    POST http://localhost:9999/ask
    Content-Type: application/json
    {"q": "<full description of the action>"}

A new fullscreen Terminal window pops up running a curses TUI with the same
look as Claude Code's permission prompt. You answer with arrow keys / 1 / 2 /
Enter / Esc; the window closes the moment you answer.

Modes:
    claude_qte.py                 # server mode (default)
    claude_qte.py --tui <rid>     # TUI mode (spawned by the server)
"""

import argparse
import curses
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote_plus, urlparse

PORT_DEFAULT = 9999
TMP_DIR = os.path.join(tempfile.gettempdir(), "claude-qte")
ANSWER_TIMEOUT = 300  # seconds the server waits for the TUI to respond


# ─── Server mode ──────────────────────────────────────────────────────────────

class ApprovalHandler(BaseHTTPRequestHandler):
    server_version = "claude-qte/0.1"

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
        self._json({
            "approved": answer["approved"],
            "answer": answer["text"],
            "message": answer["text"],
        })

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


_request_lock = threading.Lock()
_request_seq = 0


def next_request_id() -> str:
    global _request_seq
    with _request_lock:
        _request_seq += 1
        return f"{int(time.time())}-{_request_seq}-{os.getpid()}"


def prompt_user(question: str) -> dict:
    """Spawn a fullscreen Terminal window with the TUI and wait for its answer."""
    os.makedirs(TMP_DIR, exist_ok=True)
    rid = next_request_id()
    qfile = os.path.join(TMP_DIR, f"{rid}.q")
    afile = os.path.join(TMP_DIR, f"{rid}.a")

    with open(qfile, "w", encoding="utf-8") as fh:
        json.dump({"question": question}, fh)

    win_id = spawn_terminal_window(rid, question)

    answer = None
    deadline = time.time() + ANSWER_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(afile):
            try:
                with open(afile, "r", encoding="utf-8") as fh:
                    answer = json.load(fh)
            finally:
                _safe_unlink(afile)
                _safe_unlink(qfile)
            break
        time.sleep(0.03)

    # Brief pause so the TUI's `os._exit(0)` fully tears down the exec'd
    # Python process before we ask Terminal to close the window. With no
    # process left in the tty, `close saving no` skips the
    # "process still running" confirmation dialog.
    time.sleep(0.08)
    close_terminal_window(win_id)

    if answer is None:
        _safe_unlink(qfile)
        return {"approved": False, "text": "timeout"}
    return answer


def close_terminal_window(window_id: str):
    if not window_id:
        return
    script = f'''
tell application "Terminal"
    try
        close (every window whose id is {window_id}) saving no
    end try
end tell
'''
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _safe_unlink(path: str):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


# Fixed UI rows around the question panel: header (2) + spacer (1) +
# "Tool use" label (1) + panel borders (2) + scroll-hint slot (1) +
# "Do you want to proceed?" (1) + 2 options (2) + spacer (1) +
# footer separator (1) + key hints (1) + outer padding (1).
CHROME_ROWS = 14

# Window size clamps. min_cols ≥ 72 keeps the footer key-hint line on
# one line; max keeps the window from feeling oversized for long pastes.
MIN_COLS, MAX_COLS = 72, 110
MIN_ROWS, MAX_ROWS = 16, 40


def compute_window_size(question: str) -> tuple:
    """Pick (columns, rows) that fit the question without wasted space."""
    paragraphs = question.splitlines() or [""]
    longest = max((len(p) for p in paragraphs), default=0)

    # Width: the longest line plus a little breathing room, clamped.
    target_cols = max(MIN_COLS, min(MAX_COLS, longest + 10))

    # Mirror the TUI's wrap width so our row estimate is accurate.
    pad_x = max(2, (target_cols - 96) // 2)
    inner_w = target_cols - pad_x * 2
    wrap_w = max(20, inner_w - 4)

    wrapped_lines = 0
    for paragraph in paragraphs:
        if not paragraph:
            wrapped_lines += 1
            continue
        wrapped_lines += len(textwrap.wrap(
            paragraph, width=wrap_w, break_long_words=True
        ) or [""])

    target_rows = max(MIN_ROWS, min(MAX_ROWS, CHROME_ROWS + wrapped_lines))
    return target_cols, target_rows


def spawn_terminal_window(rid: str, question: str) -> str:
    """Open a Terminal.app window sized to the question, centered on screen.

    Returns the AppleScript window id (as a string), used later to close
    exactly that window without ambiguity.
    """
    cols, rows = compute_window_size(question)

    binary = current_invocation()
    quoted = " ".join(_shell_quote(part) for part in binary + ["--tui", rid])
    # `exec` replaces the shell with our Python TUI, so when Python exits
    # there is no leftover shell process in the tty.
    inner = f"clear; exec {quoted}"

    applescript = f'''
on run
    tell application "Finder"
        set sb to bounds of window of desktop
    end tell
    set sw to (item 3 of sb) - (item 1 of sb)
    set sh to (item 4 of sb) - (item 2 of sb)

    tell application "Terminal"
        activate
        set newTab to do script {_as_string(inner)}
        delay 0.05
        try
            set targetWindow to first window where tabs contains newTab
            set number of columns of targetWindow to {cols}
            set number of rows of targetWindow to {rows}
            delay 0.02
            set wb to bounds of targetWindow
            set ww to (item 3 of wb) - (item 1 of wb)
            set wh to (item 4 of wb) - (item 2 of wb)
            set wx to ((sw - ww) / 2) as integer
            set wy to ((sh - wh) / 2) as integer
            set position of targetWindow to {{wx, wy}}
            return (id of targetWindow as string)
        on error
            return ""
        end try
    end tell
end run
'''
    proc = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip()


def current_invocation() -> list:
    """Return argv-shaped command that re-launches this program."""
    if getattr(sys, "frozen", False):
        # PyInstaller-bundled binary
        return [sys.executable]
    return [sys.executable, os.path.abspath(__file__)]


def _shell_quote(s: str) -> str:
    if not s:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _as_string(s: str) -> str:
    """Quote a string for AppleScript."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_server(port: int):
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte currently supports macOS only.\n")
        sys.exit(2)
    if not shutil.which("osascript"):
        sys.stderr.write("osascript not found. claude-qte requires macOS Terminal scripting.\n")
        sys.exit(2)

    os.makedirs(TMP_DIR, exist_ok=True)
    httpd = HTTPServer(("127.0.0.1", port), ApprovalHandler)
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
        print("\nShutting down.")
        httpd.server_close()


# ─── TUI mode ─────────────────────────────────────────────────────────────────

ACCENT_FG = 208       # 256-color orange (Claude Code-ish)
DIM_FG = 244
TEXT_FG = 252
PANEL_BG = 234
ACCENT_PAIR = 1
DIM_PAIR = 2
TEXT_PAIR = 3
PANEL_PAIR = 4
SELECT_PAIR = 5

OPTIONS = [
    ("1. Yes", True),
    ("2. No, and tell Claude what to do differently", False),
]


def run_tui(rid: str):
    qfile = os.path.join(TMP_DIR, f"{rid}.q")
    afile = os.path.join(TMP_DIR, f"{rid}.a")

    if not os.path.exists(qfile):
        sys.stderr.write(f"claude-qte TUI: question file not found: {qfile}\n")
        sys.exit(1)

    with open(qfile, "r", encoding="utf-8") as fh:
        question = json.load(fh).get("question", "").strip()

    answer = curses.wrapper(_tui_loop, question)

    with open(afile, "w", encoding="utf-8") as fh:
        json.dump(answer, fh)
        fh.flush()
        os.fsync(fh.fileno())

    # Exit immediately so the tty has no live process when the server closes
    # the window. Skipping atexit/finalizers is intentional.
    os._exit(0)


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(ACCENT_PAIR, ACCENT_FG, -1)
    curses.init_pair(DIM_PAIR, DIM_FG, -1)
    curses.init_pair(TEXT_PAIR, TEXT_FG, -1)
    curses.init_pair(PANEL_PAIR, TEXT_FG, PANEL_BG)
    curses.init_pair(SELECT_PAIR, ACCENT_FG, PANEL_BG)


def _tui_loop(stdscr, question: str) -> dict:
    curses.curs_set(0)
    stdscr.keypad(True)
    _init_colors()

    selected = 0
    scroll = 0
    custom_reply_mode = False
    custom_text = ""

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        scroll = _draw_frame(stdscr, question, selected, scroll,
                             custom_reply_mode, custom_text)

        stdscr.refresh()

        ch = stdscr.get_wch()

        if custom_reply_mode:
            if ch in ("\n", "\r", curses.KEY_ENTER):
                return {"approved": False, "text": custom_text.strip() or "denied"}
            if ch == "\x1b":  # Esc cancels the typed reply, returns to options
                custom_reply_mode = False
                custom_text = ""
                continue
            if ch in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                custom_text = custom_text[:-1]
                continue
            if isinstance(ch, str) and ch.isprintable():
                custom_text += ch
            continue

        # Option-select mode
        if ch in (curses.KEY_UP, "k"):
            selected = (selected - 1) % len(OPTIONS)
        elif ch in (curses.KEY_DOWN, "j"):
            selected = (selected + 1) % len(OPTIONS)
        elif ch == "1":
            return {"approved": True, "text": "approved"}
        elif ch == "2":
            custom_reply_mode = True
        elif ch in ("\n", "\r", curses.KEY_ENTER):
            if OPTIONS[selected][1]:
                return {"approved": True, "text": "approved"}
            custom_reply_mode = True
        elif ch == "\x1b":
            custom_reply_mode = True


def _draw_frame(stdscr, question: str, selected: int, scroll: int,
                custom_mode: bool, custom_text: str) -> int:
    h, w = stdscr.getmaxyx()
    if h < 12 or w < 50:
        try:
            stdscr.addstr(0, 0, "Window too small. Resize and try again.",
                          curses.color_pair(ACCENT_PAIR))
        except curses.error:
            pass
        return scroll

    pad_x = max(2, (w - 96) // 2)
    inner_w = w - pad_x * 2
    y = 1

    # Header
    _safe_addstr(stdscr, y, pad_x, "✻ ", curses.color_pair(ACCENT_PAIR) | curses.A_BOLD)
    _safe_addstr(stdscr, y, pad_x + 2, "Claude Code",
                 curses.color_pair(TEXT_PAIR) | curses.A_BOLD)
    right_label = "permission required"
    _safe_addstr(stdscr, y, pad_x + inner_w - len(right_label),
                 right_label, curses.color_pair(DIM_PAIR))
    y += 1
    _safe_addstr(stdscr, y, pad_x, "─" * inner_w, curses.color_pair(DIM_PAIR))
    y += 2

    # Section label
    _safe_addstr(stdscr, y, pad_x, "Tool use", curses.color_pair(DIM_PAIR))
    y += 1

    # Panel border (top)
    panel_w = inner_w
    _safe_addstr(stdscr, y, pad_x,
                 "╭" + "─" * (panel_w - 2) + "╮",
                 curses.color_pair(DIM_PAIR))
    y += 1
    panel_top = y

    options_h = len(OPTIONS) + (3 if custom_mode else 0)
    footer_h = 4
    panel_max_h = max(3, h - panel_top - 1 - 4 - options_h - footer_h)

    wrapped = _wrap(question, panel_w - 4)
    visible = wrapped[scroll:scroll + panel_max_h]

    for i in range(panel_max_h):
        line = visible[i] if i < len(visible) else ""
        text = "│ " + line.ljust(panel_w - 4) + " │"
        attr = curses.color_pair(TEXT_PAIR) if i < len(visible) else curses.color_pair(DIM_PAIR)
        _safe_addstr(stdscr, panel_top + i, pad_x, text, attr)

    y = panel_top + panel_max_h
    _safe_addstr(stdscr, y, pad_x,
                 "╰" + "─" * (panel_w - 2) + "╯",
                 curses.color_pair(DIM_PAIR))
    y += 1

    # Scroll hint
    if len(wrapped) > panel_max_h:
        hint = f"({scroll + 1}–{min(len(wrapped), scroll + panel_max_h)} of {len(wrapped)} lines · PgUp/PgDn to scroll)"
        _safe_addstr(stdscr, y, pad_x, hint, curses.color_pair(DIM_PAIR))
    y += 1

    # Options
    _safe_addstr(stdscr, y, pad_x, "Do you want to proceed?",
                 curses.color_pair(TEXT_PAIR))
    y += 1
    for i, (label, _) in enumerate(OPTIONS):
        is_sel = (i == selected) and not custom_mode
        caret = "❯ " if is_sel else "  "
        attr = curses.color_pair(ACCENT_PAIR) | curses.A_BOLD if is_sel else curses.color_pair(TEXT_PAIR)
        _safe_addstr(stdscr, y, pad_x, caret + label, attr)
        y += 1

    # Custom reply input
    if custom_mode:
        y += 1
        _safe_addstr(stdscr, y, pad_x, "↳ Reply to Claude:",
                     curses.color_pair(DIM_PAIR))
        y += 1
        max_input_w = panel_w - 4
        shown = custom_text[-max_input_w:]
        _safe_addstr(stdscr, y, pad_x,
                     "│ " + shown + "█",
                     curses.color_pair(ACCENT_PAIR))
        y += 1

    # Footer
    footer_y = h - 2
    _safe_addstr(stdscr, footer_y - 1, pad_x,
                 "─" * inner_w, curses.color_pair(DIM_PAIR))
    if custom_mode:
        keys = "⏎ send to Claude   esc cancel"
    else:
        keys = "↑↓ select   ⏎ confirm   1 allow   2 deny+reply   esc deny+reply"
    _safe_addstr(stdscr, footer_y, pad_x, keys, curses.color_pair(DIM_PAIR))

    return scroll


def _wrap(text: str, width: int) -> list:
    if width <= 1:
        return [text]
    out = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            out.append("")
            continue
        out.extend(textwrap.wrap(paragraph, width=width,
                                 break_long_words=True,
                                 replace_whitespace=False) or [""])
    return out


def _safe_addstr(stdscr, y: int, x: int, text: str, attr=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    try:
        stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
    except curses.error:
        pass


# ─── Hook mode (Claude Code PreToolUse) ──────────────────────────────────────

# How long the user can be away from the keyboard / off the terminal before
# we assume they aren't watching and pop up the QTE window.
USER_PRESENCE_IDLE_SECONDS = 20

# AppleScript that returns the tty of the foreground session if the
# frontmost app is a known terminal — otherwise an empty string.
_FRONTMOST_TTY_SCRIPT = '''
tell application "System Events"
    set frontApp to name of first process whose frontmost is true
end tell
if frontApp is "Terminal" then
    try
        tell application "Terminal"
            return tty of selected tab of front window
        end tell
    end try
else if frontApp is "iTerm2" or frontApp is "iTerm" then
    try
        tell application "iTerm"
            return tty of current session of current window
        end tell
    end try
end if
return ""
'''


def run_hook(port: int):
    """PreToolUse hook entry point. Reads JSON event on stdin, decides whether
    to defer to the native prompt or to ask the popup gate."""
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # Malformed input — fail safe to native flow.
        _emit_decision("ask")
        return

    # The user may instruct Claude (via CLAUDE.md) to curl the gate before
    # each action. Installing claude-qte already implies consent for that
    # self-call, so auto-allow it — the *actual* command will hit the hook
    # again and get prompted there.
    if _is_gate_self_call(event, port):
        _emit_decision("allow", "claude-qte gate self-call")
        return

    if _user_is_present():
        _emit_decision("ask")
        return

    question = _describe_tool(event.get("tool_name", ""), event.get("tool_input", {}))
    answer = _call_gate(port, question)

    if answer is None:
        # Gate unreachable — fail safe to native flow so Claude Code keeps
        # working even if the user hasn't started the gate yet.
        _emit_decision("ask")
        return

    if answer.get("approved"):
        _emit_decision("allow", answer.get("answer") or "approved via claude-qte")
    else:
        _emit_decision("deny", answer.get("answer") or "denied via claude-qte")


def _is_gate_self_call(event: dict, port: int) -> bool:
    if event.get("tool_name") != "Bash":
        return False
    cmd = ((event.get("tool_input") or {}).get("command") or "")
    for host in ("localhost", "127.0.0.1"):
        for path in ("/ask", "/ping"):
            if f"{host}:{port}{path}" in cmd:
                return True
    return False


def _emit_decision(decision: str, reason: str = ""):
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


def _user_is_present() -> bool:
    """True iff the user is at the keyboard AND looking at the terminal where
    Claude Code is running."""
    if _idle_seconds() > USER_PRESENCE_IDLE_SECONDS:
        return False
    parent_tty = _parent_tty()
    if not parent_tty:
        return False
    front_tty = _frontmost_terminal_tty()
    return bool(front_tty) and parent_tty == front_tty


def _idle_seconds() -> float:
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return 0.0
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            try:
                return int(line.split("=")[-1].strip()) / 1e9
            except ValueError:
                return 0.0
    return 0.0


def _parent_tty() -> str:
    try:
        ppid = os.getppid()
        out = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(ppid)],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    if not out or out == "?":
        return ""
    return out if out.startswith("/dev/") else f"/dev/{out}"


def _frontmost_terminal_tty() -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", _FRONTMOST_TTY_SCRIPT],
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _describe_tool(tool_name: str, tool_input: dict) -> str:
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


def _call_gate(port: int, question: str):
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


# ─── Install / Uninstall ─────────────────────────────────────────────────────

INSTALL_BIN_DIR = os.path.expanduser("~/.local/bin")
INSTALL_BIN_NAME = "claude-qte"
PLIST_LABEL = "com.claudeqte.gate"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist")
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
# We identify our hook entry by looking for this substring inside the
# `command` string, so we don't have to add fields Claude Code might reject.
HOOK_COMMAND_MARKER = "claude-qte hook"


def run_install():
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte install is macOS-only.\n")
        sys.exit(2)

    bin_path = _install_binary()
    _install_launch_agent(bin_path)
    _patch_settings_json(bin_path)

    print(f"""
  claude-qte installed.

  • Binary:       {bin_path}
  • LaunchAgent:  {PLIST_PATH}
  • Hook in:      {SETTINGS_PATH}

  The gate is running in the background and will start at every login.
  Open a new Claude Code session — when you wander off and Claude needs
  permission, the QTE popup will appear.
""")
    if INSTALL_BIN_DIR not in os.environ.get("PATH", "").split(":"):
        print(f"  Note: add {INSTALL_BIN_DIR} to your PATH to run `claude-qte` directly.\n")


def run_uninstall():
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte uninstall is macOS-only.\n")
        sys.exit(2)

    # 1. Stop and remove the LaunchAgent.
    if os.path.exists(PLIST_PATH):
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", PLIST_PATH],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.unlink(PLIST_PATH)
        print(f"  Removed LaunchAgent {PLIST_PATH}")

    # 2. Remove the hook from settings.json.
    _unpatch_settings_json()

    # 3. Remove the binary.
    bin_path = os.path.join(INSTALL_BIN_DIR, INSTALL_BIN_NAME)
    if os.path.exists(bin_path):
        os.unlink(bin_path)
        print(f"  Removed {bin_path}")

    print("\n  claude-qte uninstalled.\n")


def _install_binary() -> str:
    os.makedirs(INSTALL_BIN_DIR, exist_ok=True)
    target = os.path.join(INSTALL_BIN_DIR, INSTALL_BIN_NAME)
    src = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)

    # Copy ourselves into ~/.local/bin if we're not already there.
    if os.path.realpath(src) != os.path.realpath(target):
        shutil.copy2(src, target)
    os.chmod(target, 0o755)

    # Strip Gatekeeper quarantine so the binary runs without "are you sure?".
    subprocess.run(
        ["xattr", "-d", "com.apple.quarantine", target],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return target


def _install_launch_agent(bin_path: str):
    plist_dir = os.path.dirname(PLIST_PATH)
    os.makedirs(plist_dir, exist_ok=True)

    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/claude-qte.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-qte.err.log</string>
</dict>
</plist>
'''
    with open(PLIST_PATH, "w", encoding="utf-8") as fh:
        fh.write(plist)

    domain = f"gui/{os.getuid()}"
    # If a previous version is loaded, kick it out first; ignore errors.
    subprocess.run(
        ["launchctl", "bootout", domain, PLIST_PATH],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["launchctl", "bootstrap", domain, PLIST_PATH],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _patch_settings_json(bin_path: str):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])

    new_entry = {
        "matcher": "Bash|Edit|Write|NotebookEdit",
        "hooks": [
            {
                "type": "command",
                "command": f"{bin_path} hook",
                "timeout": 600,
            }
        ],
    }

    # Idempotent: replace any prior entry whose command references our binary.
    rewritten = False
    for i, group in enumerate(pre):
        for cmd in group.get("hooks") or []:
            if HOOK_COMMAND_MARKER in (cmd.get("command") or ""):
                pre[i] = new_entry
                rewritten = True
                break
        if rewritten:
            break
    if not rewritten:
        pre.append(new_entry)

    _save_settings(settings)


def _unpatch_settings_json():
    if not os.path.exists(SETTINGS_PATH):
        return
    settings = _load_settings()
    hooks = settings.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    cleaned = [
        group for group in pre
        if not any(
            HOOK_COMMAND_MARKER in (cmd.get("command") or "")
            for cmd in (group.get("hooks") or [])
        )
    ]
    if cleaned == pre:
        return
    if cleaned:
        hooks["PreToolUse"] = cleaned
    else:
        hooks.pop("PreToolUse", None)
    if not hooks:
        settings.pop("hooks", None)
    _save_settings(settings)
    print(f"  Removed claude-qte hook from {SETTINGS_PATH}")


def _load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings: dict):
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, SETTINGS_PATH)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="claude-qte — Claude Code approval gate",
    )
    sub = parser.add_subparsers(dest="cmd")

    # Default (no subcommand) → server mode.
    parser.add_argument("--port", type=int, default=PORT_DEFAULT,
                        help="HTTP port to listen on (server mode)")
    parser.add_argument("--tui", metavar="RID", default=None,
                        help=argparse.SUPPRESS)

    sub.add_parser("hook", help="Run as a Claude Code PreToolUse hook")
    sub.add_parser("install", help="Install LaunchAgent + Claude Code hook")
    sub.add_parser("uninstall", help="Undo install")

    args = parser.parse_args()

    if args.cmd == "hook":
        run_hook(args.port)
    elif args.cmd == "install":
        run_install()
    elif args.cmd == "uninstall":
        run_uninstall()
    elif args.tui:
        run_tui(args.tui)
    else:
        run_server(args.port)


if __name__ == "__main__":
    main()
