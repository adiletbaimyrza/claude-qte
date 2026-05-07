"""Server-side popup spawning.

When the gate receives an ``/ask`` request, ``prompt_user`` is called. It
hands the question off to a subprocess running the curses TUI inside a fresh
Terminal.app window, then polls a tmp file for the answer.

Splitting this from :mod:`claude_qte.tui` lets us test sizing/layout
helpers without dragging in curses.
"""

import json
import os
import textwrap
import time

from claude_qte._platform import close_terminal_window, spawn_terminal_window
from claude_qte._runtime import (
    ANSWER_TIMEOUT,
    TMP_DIR,
    next_request_id,
    safe_unlink,
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
                with open(afile, encoding="utf-8") as fh:
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
        wrapped_lines += len(textwrap.wrap(paragraph, width=wrap_w, break_long_words=True) or [""])

    target_rows = max(MIN_ROWS, min(MAX_ROWS, CHROME_ROWS + wrapped_lines))
    return target_cols, target_rows
