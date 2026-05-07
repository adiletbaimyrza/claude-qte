"""Tests for claude_qte.cli — argument parsing and dispatch."""

import sys
from unittest.mock import patch

import pytest

from claude_qte.cli import main


def _run(args):
    with patch.object(sys, "argv", ["claude-qte", *args]):
        main()


class TestVersionFlag:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(["--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "claude-qte" in out

    def test_short_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(["-v"])
        assert exc.value.code == 0


class TestHookDispatch:
    def test_hook_subcommand_calls_run_hook(self):
        with patch("claude_qte.hook.run_hook") as mock_hook:
            _run(["hook"])
        mock_hook.assert_called_once()


class TestInstallDispatch:
    def test_install_calls_run_install(self):
        with patch("claude_qte.installer.run_install") as mock_install:
            _run(["install"])
        mock_install.assert_called_once()

    def test_uninstall_calls_run_uninstall(self):
        with patch("claude_qte.installer.run_uninstall") as mock_uninstall:
            _run(["uninstall"])
        mock_uninstall.assert_called_once()

    def test_update_calls_run_update(self):
        with patch("claude_qte.installer.run_update") as mock_update:
            _run(["update"])
        mock_update.assert_called_once()

    def test_disable_calls_run_disable(self):
        with patch("claude_qte.installer.run_disable") as mock_disable:
            _run(["disable"])
        mock_disable.assert_called_once()

    def test_enable_calls_run_enable(self):
        with patch("claude_qte.installer.run_enable") as mock_enable:
            _run(["enable"])
        mock_enable.assert_called_once()


class TestRunDispatch:
    def test_run_calls_run_command(self):
        with patch("claude_qte.wrapper.run_command") as mock_run:
            _run(["run", "claude"])
        mock_run.assert_called_once_with(["claude"])


class TestSoundDispatch:
    def test_sound_list(self, capsys):
        with (
            patch("claude_qte._sound.get_sound", return_value="notification"),
            patch("claude_qte._sound.is_muted", return_value=False),
        ):
            _run(["sound", "list"])
        out = capsys.readouterr().out
        assert "notification" in out

    def test_sound_list_muted(self, capsys):
        with (
            patch("claude_qte._sound.get_sound", return_value="off"),
            patch("claude_qte._sound.is_muted", return_value=True),
        ):
            _run(["sound", "list"])
        out = capsys.readouterr().out
        assert "off" in out.lower()

    def test_sound_set_valid(self, capsys):
        with (
            patch("claude_qte._sound.set_sound", return_value=True),
            patch("claude_qte._sound.play_notification"),
        ):
            import time

            with patch.object(time, "sleep"):
                _run(["sound", "set", "quack"])
        out = capsys.readouterr().out
        assert "quack" in out

    def test_sound_set_invalid_exits(self, capsys):
        with (
            patch("claude_qte._sound.set_sound", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            _run(["sound", "set", "not_a_sound"])
        assert exc.value.code == 1

    def test_sound_off(self, capsys):
        with patch("claude_qte._sound.mute_sound"):
            _run(["sound", "off"])
        out = capsys.readouterr().out
        assert "disabled" in out

    def test_sound_on(self, capsys):
        with (
            patch("claude_qte._sound.unmute_sound"),
            patch("claude_qte._sound.get_sound", return_value="notification"),
        ):
            _run(["sound", "on"])
        out = capsys.readouterr().out
        assert "enabled" in out

    def test_sound_no_subcommand_prints_help(self, capsys):
        _run(["sound"])
        out = capsys.readouterr().out
        assert "list" in out


class TestServerDispatch:
    def test_no_subcommand_calls_run_server(self):
        with patch("claude_qte.server.run_server") as mock_server:
            _run([])
        mock_server.assert_called_once()

    def test_port_flag_passed_to_server(self):
        with patch("claude_qte.server.run_server") as mock_server:
            _run(["--port", "8888"])
        mock_server.assert_called_once_with(8888, parent_pid=0, quiet=False)

    def test_tui_flag_calls_run_tui(self):
        with patch("claude_qte.tui.run_tui") as mock_tui:
            _run(["--tui", "abc123"])
        mock_tui.assert_called_once_with("abc123")
