"""Tests for claude_qte._platform — all subprocess calls are mocked."""

import signal
import subprocess
from unittest.mock import MagicMock, patch

import claude_qte._platform as plat

# ── Helpers ──────────────────────────────────────────────────────────────────


def _completed(stdout="", returncode=0):
    """Return a fake CompletedProcess."""
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.returncode = returncode
    return r


# ── TestApplescriptString ─────────────────────────────────────────────────────


class TestApplescriptString:
    def test_simple_quoted(self):
        assert plat._applescript_string("hello") == '"hello"'

    def test_double_quote_escaped(self):
        assert plat._applescript_string('say "hi"') == '"say \\"hi\\""'

    def test_backslash_escaped(self):
        assert plat._applescript_string("a\\b") == '"a\\\\b"'

    def test_empty_string(self):
        assert plat._applescript_string("") == '""'


# ── TestIdleSeconds ───────────────────────────────────────────────────────────


class TestIdleSeconds:
    def test_macos_parses_ioreg_output(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        ioreg_out = "    | HIDIdleTime = 5000000000\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _completed(stdout=ioreg_out))
        assert plat.idle_seconds() == 5.0

    def test_macos_returns_zero_on_missing_tool(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)

        def _raise(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", _raise)
        assert plat.idle_seconds() == 0.0

    def test_macos_returns_zero_on_malformed_output(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _completed(stdout="no useful lines\n")
        )
        assert plat.idle_seconds() == 0.0

    def test_linux_xprintidle_success(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _completed(stdout="3500"))
        assert plat.idle_seconds() == 3.5

    def test_linux_xprintidle_missing_returns_zero(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(plat.shutil, "which", lambda name: None)
        assert plat.idle_seconds() == 0.0

    def test_linux_no_display_returns_zero(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("DISPLAY", raising=False)
        assert plat.idle_seconds() == 0.0

    def test_linux_wayland_without_display_returns_zero(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert plat.idle_seconds() == 0.0

    def test_unsupported_platform_returns_zero(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        assert plat.idle_seconds() == 0.0


# ── TestFrontmostTerminalTty ──────────────────────────────────────────────────


class TestFrontmostTerminalTty:
    def test_macos_returns_tty_from_osascript(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _completed(stdout="/dev/ttys001\n"))
        assert plat.frontmost_terminal_tty() == "/dev/ttys001"

    def test_macos_returns_empty_on_failure(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        monkeypatch.setattr(plat, "IS_LINUX", False)

        def _raise(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", _raise)
        assert plat.frontmost_terminal_tty() == ""

    def test_linux_xdotool_non_terminal_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: _completed(stdout="Mozilla Firefox")
        )
        assert plat.frontmost_terminal_tty() == ""

    def test_linux_xdotool_missing_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(plat.shutil, "which", lambda name: None)
        assert plat.frontmost_terminal_tty() == ""

    def test_linux_no_display_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("DISPLAY", raising=False)
        assert plat.frontmost_terminal_tty() == ""

    def test_linux_xdotool_terminal_match_scans_fds(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")

        call_count = {"n": 0}

        def _run(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _completed(stdout="xterm")
            return _completed(stdout="9999")

        monkeypatch.setattr(subprocess, "run", _run)
        monkeypatch.setattr(plat.os.path, "isdir", lambda p: "/9999/fd" in p)
        monkeypatch.setattr(plat.os, "listdir", lambda p: ["0"])
        monkeypatch.setattr(plat.os, "readlink", lambda p: "/dev/pts/3")

        result = plat.frontmost_terminal_tty()
        assert result == "/dev/pts/3"

    def test_unsupported_platform_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        assert plat.frontmost_terminal_tty() == ""


# ── TestDetectLinuxTerminal ───────────────────────────────────────────────────


class TestDetectLinuxTerminal:
    def test_prefers_term_program_env(self, monkeypatch):
        monkeypatch.setenv("TERM_PROGRAM", "kitty")
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert plat._detect_linux_terminal() == "kitty"

    def test_term_program_not_on_path_falls_through(self, monkeypatch):
        monkeypatch.setenv("TERM_PROGRAM", "nonexistent-term")

        def _which(name):
            return "/usr/bin/xterm" if name == "xterm" else None

        monkeypatch.setattr(plat.shutil, "which", _which)
        assert plat._detect_linux_terminal() == "xterm"

    def test_falls_through_to_first_installed(self, monkeypatch):
        monkeypatch.delenv("TERM_PROGRAM", raising=False)

        def _which(name):
            return "/usr/bin/konsole" if name == "konsole" else None

        monkeypatch.setattr(plat.shutil, "which", _which)
        assert plat._detect_linux_terminal() == "konsole"

    def test_returns_none_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(plat.shutil, "which", lambda name: None)
        assert plat._detect_linux_terminal() is None


# ── TestBuildTerminalCmdLinux ─────────────────────────────────────────────────


class TestBuildTerminalCmdLinux:
    def test_gnome_terminal(self):
        cmd = plat._build_terminal_cmd_linux("gnome-terminal", 80, 24, "my-cmd")
        assert cmd[0] == "gnome-terminal"
        assert "--geometry=80x24" in cmd
        assert "--" in cmd
        assert "exec my-cmd" in cmd[-1]

    def test_xterm(self):
        cmd = plat._build_terminal_cmd_linux("xterm", 80, 24, "my-cmd")
        assert cmd[0] == "xterm"
        assert "-geometry" in cmd
        assert "80x24" in cmd

    def test_konsole(self):
        cmd = plat._build_terminal_cmd_linux("konsole", 80, 24, "my-cmd")
        assert cmd[0] == "konsole"
        assert "--geometry=80x24" in cmd

    def test_kitty(self):
        cmd = plat._build_terminal_cmd_linux("kitty", 80, 24, "my-cmd")
        assert cmd[0] == "kitty"
        assert "initial_window_width=80" in cmd
        assert "initial_window_height=24" in cmd

    def test_alacritty_no_geometry(self):
        cmd = plat._build_terminal_cmd_linux("alacritty", 80, 24, "my-cmd")
        assert cmd[0] == "alacritty"
        assert not any("geometry" in c for c in cmd)

    def test_x_terminal_emulator(self):
        cmd = plat._build_terminal_cmd_linux("x-terminal-emulator", 80, 24, "my-cmd")
        assert cmd[0] == "x-terminal-emulator"
        assert "--geometry=80x24" in cmd


# ── TestSpawnTerminalWindowLinux ──────────────────────────────────────────────


class TestSpawnTerminalWindowLinux:
    def test_gnome_terminal_spawn_returns_pid(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(plat, "_find_xwindow_by_pid", lambda pid, **kw: "")
        monkeypatch.setattr(plat, "_center_window_linux", lambda *a, **kw: None)
        monkeypatch.setattr(plat, "_pin_window_on_top_linux", lambda *a, **kw: None)

        mock_proc = MagicMock()
        mock_proc.pid = 42

        with patch("subprocess.Popen", return_value=mock_proc):
            result = plat.spawn_terminal_window("rid-1", "Do you approve?")

        assert result == "42"

    def test_xterm_fallback_used_when_gnome_missing(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(plat, "_find_xwindow_by_pid", lambda pid, **kw: "")
        monkeypatch.setattr(plat, "_center_window_linux", lambda *a, **kw: None)
        monkeypatch.setattr(plat, "_pin_window_on_top_linux", lambda *a, **kw: None)

        def _which(name):
            return "/usr/bin/xterm" if name == "xterm" else None

        monkeypatch.setattr(plat.shutil, "which", _which)

        captured = {}

        def _popen(argv, **kw):
            captured["argv"] = argv
            m = MagicMock()
            m.pid = 99
            return m

        with patch("subprocess.Popen", side_effect=_popen):
            result = plat.spawn_terminal_window("rid-2", "question")

        assert result == "99"
        assert captured["argv"][0] == "xterm"

    def test_no_emulator_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(plat.shutil, "which", lambda name: None)
        result = plat.spawn_terminal_window("rid-3", "question")
        assert result == ""

    def test_returns_pid_colon_xwin_when_xwin_found(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(plat, "_find_xwindow_by_pid", lambda pid, **kw: "98765")
        monkeypatch.setattr(plat, "_center_window_linux", lambda *a: None)
        monkeypatch.setattr(plat, "_pin_window_on_top_linux", lambda *a: None)
        monkeypatch.setattr(plat.shutil, "which", lambda name: f"/usr/bin/{name}")

        mock_proc = MagicMock()
        mock_proc.pid = 77

        with patch("subprocess.Popen", return_value=mock_proc):
            result = plat.spawn_terminal_window("rid-x", "question?")

        assert result == "77:98765"


# ── TestCloseTerminalWindowLinux ──────────────────────────────────────────────


class TestCloseTerminalWindowLinux:
    def test_close_empty_pid_is_noop(self, monkeypatch):
        killed = []
        monkeypatch.setattr(plat.os, "kill", lambda pid, sig: killed.append((pid, sig)))
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        plat._close_terminal_window_linux("")
        assert killed == []

    def test_close_sends_sigterm(self, monkeypatch):
        killed = []

        def _kill(pid, sig):
            if sig == 0:
                raise ProcessLookupError
            killed.append((pid, sig))

        monkeypatch.setattr(plat.os, "kill", _kill)
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        plat._close_terminal_window_linux("1234")
        assert (1234, signal.SIGTERM) in killed

    def test_close_falls_back_to_sigkill(self, monkeypatch):
        killed = []

        def _kill(pid, sig):
            killed.append((pid, sig))

        monkeypatch.setattr(plat.os, "kill", _kill)
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        plat._close_terminal_window_linux("5678")
        assert (5678, signal.SIGTERM) in killed
        assert (5678, signal.SIGKILL) in killed

    def test_close_invalid_pid_str_is_noop(self, monkeypatch):
        killed = []
        monkeypatch.setattr(plat.os, "kill", lambda pid, sig: killed.append((pid, sig)))
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        plat._close_terminal_window_linux("not-a-number")
        assert killed == []


# ── TestParseLinuxHandle ──────────────────────────────────────────────────────


class TestParseLinuxHandle:
    def test_pid_and_xwin(self):
        pid, xwin = plat._parse_linux_handle("123:0x00abc")
        assert pid == 123
        assert xwin == "0x00abc"

    def test_pid_only(self):
        pid, xwin = plat._parse_linux_handle("456")
        assert pid == 456
        assert xwin == ""

    def test_invalid_returns_zeros(self):
        pid, xwin = plat._parse_linux_handle("notanumber")
        assert pid == 0
        assert xwin == ""

    def test_colon_with_invalid_pid(self):
        pid, xwin = plat._parse_linux_handle("bad:xwin")
        assert pid == 0
        assert xwin == ""


# ── TestKeepWindowOnTop ───────────────────────────────────────────────────────


class TestKeepWindowOnTop:
    def test_linux_calls_raise_window(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_LINUX", True)
        raised = []
        monkeypatch.setattr(plat, "raise_window_linux", lambda xwin_id: raised.append(xwin_id))
        plat.keep_window_on_top("42:0xabc")
        assert raised == ["0xabc"]

    def test_linux_empty_handle_no_raise(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_LINUX", True)
        raised = []
        monkeypatch.setattr(plat, "raise_window_linux", lambda xwin_id: raised.append(xwin_id))
        plat.keep_window_on_top("")
        assert raised == [""]

    def test_non_linux_is_noop(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_LINUX", False)
        called = []
        monkeypatch.setattr(plat, "raise_window_linux", lambda *a: called.append(True))
        plat.keep_window_on_top("42:0xabc")
        assert called == []


# ── TestCenterWindowLinux ─────────────────────────────────────────────────────


class TestCenterWindowLinux:
    def test_wayland_is_noop(self, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        ran = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: ran.append(True))
        plat._center_window_linux(80, 24)
        assert ran == []

    def test_calls_wmctrl_when_xdpyinfo_succeeds(self, monkeypatch):
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        xdpyinfo_out = "  dimensions:    1920x1080 pixels\n"

        def _run(cmd, **kw):
            r = MagicMock()
            r.stdout = xdpyinfo_out if "xdpyinfo" in cmd else ""
            r.returncode = 0
            return r

        ran = []

        def _patched_run(cmd, **kw):
            ran.append(cmd[0])
            return _run(cmd, **kw)

        monkeypatch.setattr(subprocess, "run", _patched_run)
        plat._center_window_linux(80, 24)
        assert "wmctrl" in ran


# ── TestGetActiveXwindowId ────────────────────────────────────────────────────


class TestGetActiveXwindowId:
    def test_returns_id_when_digit(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(stdout="123456\n"))
        assert plat._get_active_xwindow_id() == "123456"

    def test_returns_empty_when_non_digit(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(stdout="not-a-number\n"))
        assert plat._get_active_xwindow_id() == ""

    def test_returns_empty_on_error(self, monkeypatch):
        def _raise(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", _raise)
        assert plat._get_active_xwindow_id() == ""


# ── TestPinWindowOnTopLinux ───────────────────────────────────────────────────


class TestPinWindowOnTopLinux:
    def test_empty_xwin_id_is_noop(self, monkeypatch):
        ran = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: ran.append(True))
        plat._pin_window_on_top_linux("")
        assert ran == []

    def test_calls_wmctrl_and_xdotool(self, monkeypatch):
        ran = []

        def _run(cmd, **kw):
            ran.append(cmd[0])
            return MagicMock()

        monkeypatch.setattr(subprocess, "run", _run)
        plat._pin_window_on_top_linux("12345")
        assert "wmctrl" in ran
        assert "xdotool" in ran


# ── TestRaiseWindowLinux ──────────────────────────────────────────────────────


class TestRaiseWindowLinux:
    def test_empty_xwin_is_noop(self, monkeypatch):
        ran = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: ran.append(True))
        plat.raise_window_linux("")
        assert ran == []

    def test_calls_xdotool_windowraise(self, monkeypatch):
        ran = []

        def _run(cmd, **kw):
            ran.append(cmd)
            return MagicMock()

        monkeypatch.setattr(subprocess, "run", _run)
        plat.raise_window_linux("99999")
        assert any("windowraise" in c for cmd in ran for c in cmd)


# ── TestFindPtyFromPid ────────────────────────────────────────────────────────


class TestFindPtyFromPid:
    def test_returns_pts_path(self, monkeypatch):
        monkeypatch.setattr(plat.os.path, "isdir", lambda p: True)
        monkeypatch.setattr(plat.os, "listdir", lambda p: ["3"])
        monkeypatch.setattr(plat.os, "readlink", lambda p: "/dev/pts/5")
        assert plat._find_pty_from_pid("1234") == "/dev/pts/5"

    def test_returns_empty_when_no_pts(self, monkeypatch):
        monkeypatch.setattr(plat.os.path, "isdir", lambda p: True)
        monkeypatch.setattr(plat.os, "listdir", lambda p: ["3"])
        monkeypatch.setattr(plat.os, "readlink", lambda p: "/dev/null")
        assert plat._find_pty_from_pid("1234") == ""

    def test_returns_empty_for_invalid_pid(self):
        assert plat._find_pty_from_pid("not_a_pid") == ""


# ── TestCloseTerminalWindowPublicApi ──────────────────────────────────────────


class TestCloseTerminalWindowPublicApi:
    def test_linux_dispatches_to_linux_impl(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", True)
        called = []
        monkeypatch.setattr(plat, "_close_terminal_window_linux", lambda h: called.append(h))
        plat.close_terminal_window("123")
        assert called == ["123"]

    def test_macos_dispatches_to_macos_impl(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", True)
        called = []
        monkeypatch.setattr(plat, "_close_terminal_window_macos", lambda h: called.append(h))
        plat.close_terminal_window("win-id")
        assert called == ["win-id"]


# ── TestSpawnTerminalWindowPublicApi ──────────────────────────────────────────


class TestSpawnTerminalWindowPublicApi:
    def test_unsupported_platform_returns_empty(self, monkeypatch):
        monkeypatch.setattr(plat, "IS_MACOS", False)
        monkeypatch.setattr(plat, "IS_LINUX", False)
        assert plat.spawn_terminal_window("rid", "q") == ""
