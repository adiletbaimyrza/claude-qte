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


def _spawn_terminal_window_macos(rid: str, question: str) -> str:
    """Open a Terminal.app window sized to the question, centered on screen.

    Returns the AppleScript window id (as a string) used later to close it.
    """
    from claude_qte._runtime import current_invocation, shell_quote
    from claude_qte.popup import compute_window_size

    cols, rows = compute_window_size(question)
    binary = current_invocation()
    quoted = " ".join(shell_quote(part) for part in [*binary, "--tui", rid])
    inner = f"clear; exec {quoted}"

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
"""
    proc = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


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


def _idle_seconds_linux() -> float:
    # xprintidle only works under X11; on Wayland we conservatively return 0.0
    # so that user_is_present() continues to the tty comparison check.
    if not os.environ.get("DISPLAY"):
        return 0.0
    if not shutil.which("xprintidle"):
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
    if not os.environ.get("DISPLAY"):
        return ""
    if not shutil.which("xdotool"):
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
        win_pid = pid_out.stdout.strip()
        if not win_pid:
            return ""
        fd_dir = f"/proc/{win_pid}/fd"
        if not os.path.isdir(fd_dir):
            return ""
        for fd_name in os.listdir(fd_dir):
            with contextlib.suppress(OSError):
                target = os.readlink(os.path.join(fd_dir, fd_name))
                if target.startswith("/dev/pts/"):
                    return target
    except (subprocess.SubprocessError, FileNotFoundError, PermissionError):
        pass
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
    if not shutil.which("wmctrl") or not shutil.which("xdpyinfo"):
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
        # Approximate pixel size: 8px per col, 16px per row (good enough for centering).
        win_w = cols * 8
        win_h = rows * 16
        cx = max(0, (screen_w - win_w) // 2)
        cy = max(0, (screen_h - win_h) // 2)
        subprocess.run(
            ["wmctrl", "-r", ":ACTIVE:", "-e", f"0,{cx},{cy},{win_w},{win_h}"],
            check=False,
            timeout=2,
        )
    except Exception:
        pass


def _spawn_terminal_window_linux(rid: str, question: str) -> str:
    """Spawn a terminal emulator running the TUI. Returns str(pid) or ''."""
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

    # Best-effort centering: wait briefly for the window to appear, then move it.
    time.sleep(0.2)
    _center_window_linux(cols, rows)

    return str(proc.pid)


def _close_terminal_window_linux(pid_str: str) -> None:
    if not pid_str:
        return
    try:
        pid = int(pid_str)
    except ValueError:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGTERM)
    time.sleep(0.15)
    # If the process is still alive, escalate to SIGKILL.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, 0)  # raises ProcessLookupError if already gone
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


def spawn_terminal_window(rid: str, question: str) -> str:
    """Spawn a terminal window running the TUI for *rid*.

    Returns an opaque handle string passed back to :func:`close_terminal_window`.
    On macOS this is the AppleScript window id; on Linux it is the process PID.
    Returns '' on failure — callers must handle that gracefully.
    """
    if IS_MACOS:
        return _spawn_terminal_window_macos(rid, question)
    if IS_LINUX:
        return _spawn_terminal_window_linux(rid, question)
    return ""


def close_terminal_window(handle: str) -> None:
    """Close the terminal window identified by *handle* from spawn_terminal_window."""
    if IS_MACOS:
        _close_terminal_window_macos(handle)
    elif IS_LINUX:
        _close_terminal_window_linux(handle)
