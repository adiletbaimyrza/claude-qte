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


# ── TestApplescriptString (moved from test_runtime) ──────────────────────────


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
        # Window name is a browser — not a terminal.
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
                return _completed(stdout="xterm")  # window name
            return _completed(stdout="9999")  # window pid

        monkeypatch.setattr(subprocess, "run", _run)

        # Fake out the /proc/9999/fd scan without touching the real filesystem.
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
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        monkeypatch.setattr(plat, "_center_window_linux", lambda *a, **kw: None)
        monkeypatch.setattr(plat, "_get_active_xwindow_id", lambda: "")
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
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        monkeypatch.setattr(plat, "_center_window_linux", lambda *a, **kw: None)
        monkeypatch.setattr(plat, "_get_active_xwindow_id", lambda: "")
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
                raise ProcessLookupError  # process already gone after SIGTERM
            killed.append((pid, sig))

        monkeypatch.setattr(plat.os, "kill", _kill)
        monkeypatch.setattr(plat.time, "sleep", lambda _: None)
        plat._close_terminal_window_linux("1234")
        assert (1234, signal.SIGTERM) in killed

    def test_close_falls_back_to_sigkill(self, monkeypatch):
        killed = []

        def _kill(pid, sig):
            killed.append((pid, sig))  # os.kill(pid, 0) does NOT raise → process alive

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
