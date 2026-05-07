"""Server-side popup spawning.

When the gate receives an ``/ask`` request, ``prompt_user`` is called. It
hands the question off to a subprocess running the curses TUI inside a fresh
Terminal.app window, then polls a tmp file for the answer.

Splitting this from :mod:`claude_qte.tui` lets us test sizing/layout
helpers without dragging in curses.
"""

import json
import os
import subprocess
import textwrap
import time

from claude_qte._runtime import (
    ANSWER_TIMEOUT,
    TMP_DIR,
    applescript_string,
    current_invocation,
    next_request_id,
    safe_unlink,
    shell_quote,
)

# Fixed UI rows around the question panel: header (2) + spacer (1) +
# "Tool use" label (1) + panel borders (2) + scroll-hint slot (1) +
# "Do you want to proceed?" (1) + 2 options (2) + spacer (1) +
# footer separator (1) + key hints (1) + outer padding (1).
CHROME_ROWS = 14

# Window size clamps. min_cols ≥ 72 keeps the footer key-hint line on
# one line; max keeps the window from feeling oversized for long pastes.
MIN_COLS, MAX_COLS = 72, 110
MIN_ROWS, MAX_ROWS = 16, 40


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
                safe_unlink(afile)
                safe_unlink(qfile)
            break
        time.sleep(0.03)

    # Brief pause so the TUI's `os._exit(0)` fully tears down the exec'd
    # Python process before we ask Terminal to close the window. With no
    # process left in the tty, `close saving no` skips the
    # "process still running" confirmation dialog.
    time.sleep(0.08)
    close_terminal_window(win_id)

    if answer is None:
        safe_unlink(qfile)
        return {"approved": False, "text": "timeout"}
    return answer


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
    quoted = " ".join(shell_quote(part) for part in binary + ["--tui", rid])
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
        set newTab to do script {applescript_string(inner)}
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


def close_terminal_window(window_id: str) -> None:
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
