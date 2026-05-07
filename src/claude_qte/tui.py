"""Curses TUI rendered inside the spawned Terminal window.

Runs as ``claude-qte --tui <rid>``: reads the question from a tmp file,
draws a Claude-Code-style prompt, writes the answer back, and exits.
"""

import contextlib
import curses
import json
import os
import sys
import textwrap

from claude_qte._runtime import TMP_DIR

ACCENT_FG = 208  # 256-color orange (Claude Code-ish)
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


def run_tui(rid: str) -> None:
    qfile = os.path.join(TMP_DIR, f"{rid}.q")
    afile = os.path.join(TMP_DIR, f"{rid}.a")

    if not os.path.exists(qfile):
        sys.stderr.write(f"claude-qte TUI: question file not found: {qfile}\n")
        sys.exit(1)

    with open(qfile, encoding="utf-8") as fh:
        question = json.load(fh).get("question", "").strip()

    answer = curses.wrapper(_tui_loop, question)

    with open(afile, "w", encoding="utf-8") as fh:
        json.dump(answer, fh)
        fh.flush()
        os.fsync(fh.fileno())

    # Exit immediately so the tty has no live process when the server closes
    # the window. Skipping atexit/finalizers is intentional.
    os._exit(0)


def _init_colors() -> None:
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
        scroll = _draw_frame(stdscr, question, selected, scroll, custom_reply_mode, custom_text)
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


def _draw_frame(
    stdscr, question: str, selected: int, scroll: int, custom_mode: bool, custom_text: str
) -> int:
    h, w = stdscr.getmaxyx()
    if h < 12 or w < 50:
        with contextlib.suppress(curses.error):
            stdscr.addstr(
                0, 0, "Window too small. Resize and try again.", curses.color_pair(ACCENT_PAIR)
            )
        return scroll

    pad_x = max(2, (w - 96) // 2)
    inner_w = w - pad_x * 2
    y = 1

    # Header
    _safe_addstr(stdscr, y, pad_x, "✻ ", curses.color_pair(ACCENT_PAIR) | curses.A_BOLD)
    _safe_addstr(stdscr, y, pad_x + 2, "Claude Code", curses.color_pair(TEXT_PAIR) | curses.A_BOLD)
    right_label = "permission required"
    _safe_addstr(
        stdscr, y, pad_x + inner_w - len(right_label), right_label, curses.color_pair(DIM_PAIR)
    )
    y += 1
    _safe_addstr(stdscr, y, pad_x, "─" * inner_w, curses.color_pair(DIM_PAIR))
    y += 2

    # Section label
    _safe_addstr(stdscr, y, pad_x, "Tool use", curses.color_pair(DIM_PAIR))
    y += 1

    # Panel border (top)
    panel_w = inner_w
    _safe_addstr(stdscr, y, pad_x, "╭" + "─" * (panel_w - 2) + "╮", curses.color_pair(DIM_PAIR))
    y += 1
    panel_top = y

    options_h = len(OPTIONS) + (3 if custom_mode else 0)
    footer_h = 4
    panel_max_h = max(3, h - panel_top - 1 - 4 - options_h - footer_h)

    wrapped = _wrap(question, panel_w - 4)
    visible = wrapped[scroll : scroll + panel_max_h]

    for i in range(panel_max_h):
        line = visible[i] if i < len(visible) else ""
        text = "│ " + line.ljust(panel_w - 4) + " │"
        attr = curses.color_pair(TEXT_PAIR) if i < len(visible) else curses.color_pair(DIM_PAIR)
        _safe_addstr(stdscr, panel_top + i, pad_x, text, attr)

    y = panel_top + panel_max_h
    _safe_addstr(stdscr, y, pad_x, "╰" + "─" * (panel_w - 2) + "╯", curses.color_pair(DIM_PAIR))
    y += 1

    # Scroll hint
    if len(wrapped) > panel_max_h:
        hint = f"({scroll + 1}–{min(len(wrapped), scroll + panel_max_h)} of {len(wrapped)} lines · PgUp/PgDn to scroll)"
        _safe_addstr(stdscr, y, pad_x, hint, curses.color_pair(DIM_PAIR))
    y += 1

    # Options
    _safe_addstr(stdscr, y, pad_x, "Do you want to proceed?", curses.color_pair(TEXT_PAIR))
    y += 1
    for i, (label, _) in enumerate(OPTIONS):
        is_sel = (i == selected) and not custom_mode
        caret = "❯ " if is_sel else "  "
        attr = (
            curses.color_pair(ACCENT_PAIR) | curses.A_BOLD
            if is_sel
            else curses.color_pair(TEXT_PAIR)
        )
        _safe_addstr(stdscr, y, pad_x, caret + label, attr)
        y += 1

    # Custom reply input
    if custom_mode:
        y += 1
        _safe_addstr(stdscr, y, pad_x, "↳ Reply to Claude:", curses.color_pair(DIM_PAIR))
        y += 1
        max_input_w = panel_w - 4
        shown = custom_text[-max_input_w:]
        _safe_addstr(stdscr, y, pad_x, "│ " + shown + "█", curses.color_pair(ACCENT_PAIR))
        y += 1

    # Footer
    footer_y = h - 2
    _safe_addstr(stdscr, footer_y - 1, pad_x, "─" * inner_w, curses.color_pair(DIM_PAIR))
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
        out.extend(
            textwrap.wrap(paragraph, width=width, break_long_words=True, replace_whitespace=False)
            or [""]
        )
    return out


def _safe_addstr(stdscr, y: int, x: int, text: str, attr=0) -> None:
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    with contextlib.suppress(curses.error):
        stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
