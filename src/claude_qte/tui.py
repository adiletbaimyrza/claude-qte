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
DIFF_ADD_PAIR = 6  # green for + lines
DIFF_DEL_PAIR = 7  # red for - lines
DIFF_HUNK_PAIR = 8  # cyan for @@ headers

OPTIONS = [
    ("1. Yes", True),
    ("2. No, and tell Claude what to do differently", False),
]


def _parse_question(raw: str) -> tuple:
    """Return (label, lines, is_diff) where lines is a list of (text, attr_key) pairs.

    attr_key is one of: 'text', 'add', 'del', 'hunk', 'meta'.
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("__diff__"):
            path = parsed.get("path", "")
            diff_text = parsed.get("diff", "")
            lines = []
            for line in diff_text.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    lines.append((line, "add"))
                elif line.startswith("-") and not line.startswith("---"):
                    lines.append((line, "del"))
                elif line.startswith("@@"):
                    lines.append((line, "hunk"))
                else:
                    lines.append((line, "meta"))
            return path, lines, True
    except (json.JSONDecodeError, TypeError):
        pass
    return "Tool use", [(line, "text") for line in raw.splitlines()], False


def run_tui(rid: str) -> None:
    qfile = os.path.join(TMP_DIR, f"{rid}.q")
    afile = os.path.join(TMP_DIR, f"{rid}.a")

    if not os.path.exists(qfile):
        sys.stderr.write(f"claude-qte TUI: question file not found: {qfile}\n")
        sys.exit(1)

    with open(qfile, encoding="utf-8") as fh:
        question = json.load(fh).get("question", "").strip()

    label, lines, is_diff = _parse_question(question)
    answer = curses.wrapper(_tui_loop, label, lines, is_diff)

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
    curses.init_pair(DIFF_ADD_PAIR, 2, PANEL_BG)  # green on panel bg
    curses.init_pair(DIFF_DEL_PAIR, 1, PANEL_BG)  # red on panel bg
    curses.init_pair(DIFF_HUNK_PAIR, 6, PANEL_BG)  # cyan on panel bg


def _tui_loop(stdscr, label: str, lines: list, is_diff: bool) -> dict:
    curses.curs_set(0)
    stdscr.keypad(True)
    _init_colors()

    selected = 0
    scroll = 0
    custom_reply_mode = False
    custom_text = ""

    while True:
        stdscr.erase()
        scroll, panel_max_h = _draw_frame(
            stdscr, label, lines, is_diff, selected, scroll, custom_reply_mode, custom_text
        )
        stdscr.refresh()

        ch = stdscr.get_wch()
        total_lines = len(lines)

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

        # Panel scroll (PgUp / PgDn / home / end)
        if ch == curses.KEY_PPAGE:
            scroll = max(0, scroll - panel_max_h)
        elif ch == curses.KEY_NPAGE:
            scroll = max(0, min(total_lines - panel_max_h, scroll + panel_max_h))
        elif ch == curses.KEY_HOME:
            scroll = 0
        elif ch == curses.KEY_END:
            scroll = max(0, total_lines - panel_max_h)
        # Option-select mode
        elif ch in (curses.KEY_UP, "k"):
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


_DIFF_ATTR = {
    "add": DIFF_ADD_PAIR,
    "del": DIFF_DEL_PAIR,
    "hunk": DIFF_HUNK_PAIR,
    "meta": DIM_PAIR,
    "text": TEXT_PAIR,
}


def _draw_frame(
    stdscr,
    label: str,
    lines: list,
    is_diff: bool,
    selected: int,
    scroll: int,
    custom_mode: bool,
    custom_text: str,
) -> tuple:
    h, w = stdscr.getmaxyx()
    if h < 12 or w < 50:
        with contextlib.suppress(curses.error):
            stdscr.addstr(
                0, 0, "Window too small. Resize and try again.", curses.color_pair(ACCENT_PAIR)
            )
        return scroll, 3

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

    # Section label — file path for diffs, "Tool use" for plain text
    _safe_addstr(stdscr, y, pad_x, label, curses.color_pair(DIM_PAIR))
    y += 1

    # Panel border (top)
    panel_w = inner_w
    _safe_addstr(stdscr, y, pad_x, "╭" + "─" * (panel_w - 2) + "╮", curses.color_pair(DIM_PAIR))
    y += 1
    panel_top = y

    options_h = len(OPTIONS) + (3 if custom_mode else 0)
    footer_h = 4
    panel_max_h = max(3, h - panel_top - 1 - 4 - options_h - footer_h)

    # Build visible lines: for diffs use raw tagged lines; for plain text wrap.
    if is_diff:
        all_display = lines  # list of (text, attr_key)
    else:
        all_display = [
            (wrapped_line, "text")
            for raw_line, _ in lines
            for wrapped_line in (_wrap(raw_line, panel_w - 4) or [""])
        ]

    visible = all_display[scroll : scroll + panel_max_h]

    for i in range(panel_max_h):
        if i < len(visible):
            line_text, attr_key = visible[i]
            # Truncate to fit inside the panel borders
            max_line_w = panel_w - 4
            if len(line_text) > max_line_w:
                line_text = line_text[:max_line_w]
            padded = line_text.ljust(max_line_w)
            pair = _DIFF_ATTR.get(attr_key, TEXT_PAIR)
            border_attr = curses.color_pair(DIM_PAIR)
            panel_attr = curses.color_pair(pair)
            _safe_addstr(stdscr, panel_top + i, pad_x, "│ ", border_attr)
            _safe_addstr(stdscr, panel_top + i, pad_x + 2, padded, panel_attr)
            _safe_addstr(stdscr, panel_top + i, pad_x + 2 + max_line_w, " │", border_attr)
        else:
            _safe_addstr(
                stdscr,
                panel_top + i,
                pad_x,
                "│" + " " * (panel_w - 2) + "│",
                curses.color_pair(DIM_PAIR),
            )

    y = panel_top + panel_max_h
    _safe_addstr(stdscr, y, pad_x, "╰" + "─" * (panel_w - 2) + "╯", curses.color_pair(DIM_PAIR))
    y += 1

    # Scroll hint
    total = len(all_display)
    if total > panel_max_h:
        hint = f"({scroll + 1}–{min(total, scroll + panel_max_h)} of {total} lines · PgUp/PgDn to scroll)"
        _safe_addstr(stdscr, y, pad_x, hint, curses.color_pair(DIM_PAIR))
    y += 1

    # Options
    _safe_addstr(stdscr, y, pad_x, "Do you want to proceed?", curses.color_pair(TEXT_PAIR))
    y += 1
    for i, (opt_label, _) in enumerate(OPTIONS):
        is_sel = (i == selected) and not custom_mode
        caret = "❯ " if is_sel else "  "
        attr = (
            curses.color_pair(ACCENT_PAIR) | curses.A_BOLD
            if is_sel
            else curses.color_pair(TEXT_PAIR)
        )
        _safe_addstr(stdscr, y, pad_x, caret + opt_label, attr)
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
        keys = "PgUp/PgDn scroll   ↑↓ select   ⏎ confirm   1 allow   2 deny+reply   esc deny+reply"
    _safe_addstr(stdscr, footer_y, pad_x, keys, curses.color_pair(DIM_PAIR))

    return scroll, panel_max_h


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
