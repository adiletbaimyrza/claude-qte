"""Platform-specific OS integration layer.

Provides a unified API for all OS-dependent operations. Each public function
dispatches to the correct implementation based on the current platform.
Callers never need to check ``sys.platform`` themselves.

Supported platforms
-------------------
- macOS  (``IS_MACOS``): AppleScript + Terminal.app + ioreg
- Linux  (``IS_LINUX``): xprintidle + xdotool + terminal emulator fallback chain

On unsupported platforms every function returns a safe fallback value so the
rest of the tool continues to work (falling back to the native inline prompt).
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time

IS_MACOS: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform == "linux"

# ── macOS: AppleScript that returns the tty of the foreground terminal ───────

_FRONTMOST_TTY_SCRIPT = """
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
"""


# ── macOS helpers ─────────────────────────────────────────────────────────────


def _applescript_string(s: str) -> str:
    """Quote a string for use inside an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str, *, capture: bool = False, timeout: float | None = None):
    """Run an AppleScript snippet via osascript. Returns a CompletedProcess."""
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=capture,
        text=True,
        check=False,
        timeout=timeout,
    )


def _idle_seconds_macos() -> float:
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=2,
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


def _frontmost_terminal_tty_macos() -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", _FRONTMOST_TTY_SCRIPT],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _spawn_terminal_window_macos(
    rid: str, question: str, position: tuple[int, int] | None = None
) -> str:
    """Open a Terminal.app window sized to the question.

    If *position* is given as (x, y) the window is placed there; otherwise it
    is centered on screen.  Returns the AppleScript window id (as a string).
    """
    from claude_qte._runtime import current_invocation, shell_quote
    from claude_qte.popup import compute_window_size

    cols, rows = compute_window_size(question)
    binary = current_invocation()
    quoted = " ".join(shell_quote(part) for part in [*binary, "--tui", rid])
    inner = f"clear; exec {quoted}"

    if position is not None:
        px, py = position
        position_script = f"set position of targetWindow to {{{px}, {py}}}"
    else:
        position_script = (
            "set wb to bounds of targetWindow\n"
            "            set ww to (item 3 of wb) - (item 1 of wb)\n"
            "            set wh to (item 4 of wb) - (item 2 of wb)\n"
            "            set wx to ((sw - ww) / 2) as integer\n"
            "            set wy to ((sh - wh) / 2) as integer\n"
            "            set position of targetWindow to {wx, wy}"
        )

    applescript = f"""
on run
    tell application "Finder"
        set sb to bounds of window of desktop
    end tell
    set sw to (item 3 of sb) - (item 1 of sb)
    set sh to (item 4 of sb) - (item 2 of sb)

    tell application "Terminal"
        activate
        set newTab to do script {_applescript_string(inner)}
        delay 0.05
        try
            set targetWindow to first window where tabs contains newTab
            set number of columns of targetWindow to {cols}
            set number of rows of targetWindow to {rows}
            delay 0.02
            {position_script}
            return (id of targetWindow as string)
        on error
            return ""
        end try
    end tell
end run
"""
    proc = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def _read_window_position_macos(window_id: str) -> tuple[int, int] | None:
    """Return the current (x, y) position of a Terminal.app window, or None."""
    if not window_id:
        return None
    script = f"""
tell application "Terminal"
    try
        set w to first window whose id is {window_id}
        set pos to position of w
        return ((item 1 of pos as string) & "," & (item 2 of pos as string))
    on error
        return ""
    end try
end tell
"""
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        if "," in out:
            x, y = out.split(",", 1)
            return int(x.strip()), int(y.strip())
    except Exception:
        pass
    return None


def _close_terminal_window_macos(window_id: str) -> None:
    if not window_id:
        return
    script = f"""
tell application "Terminal"
    try
        close (every window whose id is {window_id}) saving no
    end try
end tell
"""
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ── Linux helpers ─────────────────────────────────────────────────────────────

# Known terminal emulator window class / title substrings used to decide
# whether the focused X11 window is a terminal.
_TERMINAL_NAMES = frozenset(
    [
        "terminal",
        "xterm",
        "konsole",
        "gnome-terminal",
        "tilix",
        "alacritty",
        "kitty",
        "rxvt",
        "urxvt",
        "st",
        "foot",
        "wezterm",
    ]
)

# Detection order for the emulator to spawn the TUI in.
_LINUX_EMULATOR_CANDIDATES = [
    "gnome-terminal",
    "xterm",
    "konsole",
    "x-terminal-emulator",
    "kitty",
    "alacritty",
]


def _detect_linux_terminal() -> str | None:
    """Return the name of a usable terminal emulator, or None."""
    term_prog = os.environ.get("TERM_PROGRAM", "")
    if term_prog and shutil.which(term_prog):
        return term_prog
    for candidate in _LINUX_EMULATOR_CANDIDATES:
        if shutil.which(candidate):
            return candidate
    return None


def _is_x11_available() -> bool:
    return bool(os.environ.get("DISPLAY"))


def _find_pty_from_pid(pid_str: str) -> str:
    """Scan /proc/<pid>/fd for a pts symlink; return the target path or ''."""
    try:
        fd_dir = f"/proc/{int(pid_str)}/fd"
        if not os.path.isdir(fd_dir):
            return ""
        for fd_name in os.listdir(fd_dir):
            with contextlib.suppress(OSError):
                target = os.readlink(os.path.join(fd_dir, fd_name))
                if target.startswith("/dev/pts/"):
                    return target
    except (ValueError, OSError, PermissionError):
        pass
    return ""


def _idle_seconds_linux() -> float:
    # xprintidle only works under X11; on Wayland we conservatively return 0.0
    # so that user_is_present() continues to the tty comparison check.
    if not _is_x11_available():
        return 0.0
    try:
        out = subprocess.run(
            ["xprintidle"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        return int(out) / 1000.0
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        return 0.0


def _frontmost_terminal_tty_linux() -> str:
    """Return the tty of the focused terminal window, or '' if undetectable."""
    if not _is_x11_available():
        return ""
    try:
        name_out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        window_name = name_out.stdout.strip().lower()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""

    if not any(t in window_name for t in _TERMINAL_NAMES):
        return ""

    # Get the PID of the focused window's owner, then scan its open fds for a
    # pts device — that is the tty we compare against _parent_tty().
    try:
        pid_out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return _find_pty_from_pid(pid_out.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _build_terminal_cmd_linux(emulator: str, cols: int, rows: int, tui_cmd: str) -> list[str]:
    """Return the argv to launch *emulator* running *tui_cmd*."""
    geo = f"{cols}x{rows}"
    if emulator == "gnome-terminal":
        return ["gnome-terminal", f"--geometry={geo}", "--", "bash", "-c", f"exec {tui_cmd}"]
    if emulator == "xterm":
        return ["xterm", "-geometry", geo, "-e", tui_cmd]
    if emulator == "konsole":
        return ["konsole", f"--geometry={geo}", "-e", tui_cmd]
    if emulator == "kitty":
        return [
            "kitty",
            "--override",
            f"initial_window_width={cols}",
            "--override",
            f"initial_window_height={rows}",
            "bash",
            "-c",
            f"exec {tui_cmd}",
        ]
    if emulator == "alacritty":
        # alacritty does not support --geometry; size is cosmetic only.
        return ["alacritty", "-e", "bash", "-c", f"exec {tui_cmd}"]
    # x-terminal-emulator and unknown: try with --geometry; caller retries without.
    return ["x-terminal-emulator", f"--geometry={geo}", "-e", tui_cmd]


def _center_window_linux(cols: int, rows: int) -> None:
    """Best-effort X11-only window centering via wmctrl. Silently ignored on Wayland."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return
    try:
        info = subprocess.run(["xdpyinfo"], capture_output=True, text=True, timeout=2).stdout
        screen_w = screen_h = 0
        for line in info.splitlines():
            if "dimensions:" in line:
                # e.g. "  dimensions:    1920x1080 pixels"
                part = line.split(":")[1].strip().split()[0]
                screen_w, screen_h = (int(v) for v in part.split("x"))
                break
        if not screen_w:
            return
        win_w = cols * 8  # ~8px per column
        win_h = rows * 16  # ~16px per row
        cx = max(0, (screen_w - win_w) // 2)
        cy = max(0, (screen_h - win_h) // 2)
        subprocess.run(
            ["wmctrl", "-r", ":ACTIVE:", "-e", f"0,{cx},{cy},{win_w},{win_h}"],
            check=False,
            timeout=2,
        )
    except Exception:
        pass


def _place_window_linux(xwin_id: str, x: int, y: int) -> None:
    """Move an X11 window to (x, y) via wmctrl. No-op on Wayland or if unavailable."""
    if os.environ.get("WAYLAND_DISPLAY") or not xwin_id:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["wmctrl", "-i", "-r", xwin_id, "-e", f"0,{x},{y},-1,-1"],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _read_window_position_linux(xwin_id: str) -> tuple[int, int] | None:
    """Return the current (x, y) position of an X11 window via xdotool, or None."""
    if not xwin_id or os.environ.get("WAYLAND_DISPLAY"):
        return None
    try:
        out = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", xwin_id],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
        x = y = None
        for line in out.splitlines():
            if line.startswith("X="):
                x = int(line.split("=", 1)[1])
            elif line.startswith("Y="):
                y = int(line.split("=", 1)[1])
        if x is not None and y is not None:
            return x, y
    except Exception:
        pass
    return None


def _get_active_xwindow_id() -> str:
    """Return the hex window ID of the currently focused X11 window, or ''."""
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        return out if out.isdigit() else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _pin_window_on_top_linux(xwin_id: str) -> None:
    """Set _NET_WM_STATE_ABOVE and raise the window. No-op if tools unavailable."""
    if not xwin_id:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["wmctrl", "-i", "-r", xwin_id, "-b", "add,above"],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    with contextlib.suppress(Exception):
        subprocess.run(
            ["xdotool", "windowraise", xwin_id],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    with contextlib.suppress(Exception):
        subprocess.run(
            ["xdotool", "windowfocus", "--sync", xwin_id],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def raise_window_linux(xwin_id: str) -> None:
    """Re-raise a pinned window so it comes back to the front if buried."""
    if not xwin_id:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["xdotool", "windowraise", xwin_id],
            check=False,
            timeout=1,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _spawn_terminal_window_linux(
    rid: str, question: str, position: tuple[int, int] | None = None
) -> str:
    """Spawn a terminal emulator running the TUI. Returns 'pid:xwin_id' or str(pid)."""
    from claude_qte._runtime import current_invocation, shell_quote
    from claude_qte.popup import compute_window_size

    cols, rows = compute_window_size(question)
    binary = current_invocation()
    tui_cmd = " ".join(shell_quote(part) for part in [*binary, "--tui", rid])

    emulator = _detect_linux_terminal()
    if emulator is None:
        return ""

    argv = _build_terminal_cmd_linux(emulator, cols, rows, tui_cmd)
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError):
        # Geometry flag unsupported — retry without it for x-terminal-emulator.
        if emulator == "x-terminal-emulator":
            try:
                proc = subprocess.Popen(
                    ["x-terminal-emulator", "-e", tui_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except (FileNotFoundError, PermissionError):
                return ""
        else:
            return ""

    # Wait for the window to appear, then position and pin it on top.
    time.sleep(0.25)
    xwin_id = _get_active_xwindow_id()
    if position is not None:
        _place_window_linux(xwin_id, *position)
    else:
        _center_window_linux(cols, rows)
    _pin_window_on_top_linux(xwin_id)

    # Encode both pid and xwin_id so the polling loop can re-raise periodically.
    return f"{proc.pid}:{xwin_id}" if xwin_id else str(proc.pid)


def _parse_linux_handle(handle: str) -> tuple[int, str]:
    """Parse a handle returned by _spawn_terminal_window_linux into (pid, xwin_id)."""
    if ":" in handle:
        pid_part, xwin_part = handle.split(":", 1)
        try:
            return int(pid_part), xwin_part
        except ValueError:
            pass
    try:
        return int(handle), ""
    except ValueError:
        return 0, ""


def _close_terminal_window_linux(handle: str) -> None:
    if not handle:
        return
    pid, _xwin_id = _parse_linux_handle(handle)
    if not pid:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGTERM)
    # Poll briefly; SIGKILL only if the process hasn't exited yet.
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)


# ── Public API ────────────────────────────────────────────────────────────────


def idle_seconds() -> float:
    """Seconds since the last user HID input. Returns 0.0 if unavailable."""
    if IS_MACOS:
        return _idle_seconds_macos()
    if IS_LINUX:
        return _idle_seconds_linux()
    return 0.0


def frontmost_terminal_tty() -> str:
    """Tty path of the foreground terminal window, or '' if undetectable."""
    if IS_MACOS:
        return _frontmost_terminal_tty_macos()
    if IS_LINUX:
        return _frontmost_terminal_tty_linux()
    return ""


def spawn_terminal_window(rid: str, question: str, position: tuple[int, int] | None = None) -> str:
    """Spawn a terminal window running the TUI for *rid*.

    If *position* is given as (x, y) the window is placed there; otherwise it
    is centered on screen.  Returns an opaque handle string passed back to
    :func:`close_terminal_window` and :func:`read_window_position`.
    Returns '' on failure — callers must handle that gracefully.
    """
    if IS_MACOS:
        return _spawn_terminal_window_macos(rid, question, position)
    if IS_LINUX:
        return _spawn_terminal_window_linux(rid, question, position)
    return ""


def read_window_position(handle: str) -> tuple[int, int] | None:
    """Return the current (x, y) screen position of the popup window, or None."""
    if IS_MACOS:
        return _read_window_position_macos(handle)
    if IS_LINUX:
        _, xwin_id = _parse_linux_handle(handle)
        return _read_window_position_linux(xwin_id)
    return None


def close_terminal_window(handle: str) -> None:
    """Close the terminal window identified by *handle* from spawn_terminal_window."""
    if IS_MACOS:
        _close_terminal_window_macos(handle)
    elif IS_LINUX:
        _close_terminal_window_linux(handle)


def keep_window_on_top(handle: str) -> None:
    """Re-raise the popup window so it stays above other windows.

    Called periodically from the polling loop while waiting for user input.
    No-op on unsupported platforms or if the handle is empty.
    """
    if IS_LINUX:
        _, xwin_id = _parse_linux_handle(handle)
        raise_window_linux(xwin_id)
