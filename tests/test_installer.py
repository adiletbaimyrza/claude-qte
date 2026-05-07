"""Tests for claude_qte.installer."""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

import claude_qte.installer as inst_mod
from claude_qte.installer import (
    _editable_repo_path,
    _install_binary,
    _latest_github_tag,
    remove_legacy_launch_agent,
    run_update,
)


def _md_path(tmp_path):
    return str(tmp_path / "CLAUDE.md")


def _read(path):
    with open(path) as fh:
        return fh.read()


class TestPatchClaudeMd:
    def test_creates_file_if_missing(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        inst_mod.patch_claude_md()
        content = _read(path)
        assert inst_mod.CLAUDE_MD_BEGIN in content
        assert inst_mod.CLAUDE_MD_END in content

    def test_appends_block_to_existing_file(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        with open(path, "w") as fh:
            fh.write("# Existing notes\n\nSome content.\n")
        inst_mod.patch_claude_md()
        content = _read(path)
        assert "# Existing notes" in content
        assert inst_mod.CLAUDE_MD_BEGIN in content

    def test_idempotent_on_repeat(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        inst_mod.patch_claude_md()
        inst_mod.patch_claude_md()
        content = _read(path)
        assert content.count(inst_mod.CLAUDE_MD_BEGIN) == 1

    def test_replaces_stale_block(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        old_block = f"{inst_mod.CLAUDE_MD_BEGIN}\nOld content.\n{inst_mod.CLAUDE_MD_END}"
        with open(path, "w") as fh:
            fh.write(old_block)
        inst_mod.patch_claude_md()
        content = _read(path)
        assert "Old content." not in content
        assert "claude-qte" in content


class TestUnpatchClaudeMd:
    def test_removes_block(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        inst_mod.patch_claude_md()
        inst_mod.unpatch_claude_md()
        content = _read(path)
        assert inst_mod.CLAUDE_MD_BEGIN not in content

    def test_noop_when_block_absent(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        with open(path, "w") as fh:
            fh.write("# Notes\n")
        inst_mod.unpatch_claude_md()
        assert _read(path) == "# Notes\n"

    def test_noop_when_file_missing(self, monkeypatch, tmp_path):
        path = _md_path(tmp_path)
        monkeypatch.setattr(inst_mod, "CLAUDE_MD_PATH", path)
        inst_mod.unpatch_claude_md()  # must not raise
        assert not os.path.exists(path)


class TestDisableEnable:
    def test_disable_creates_flag(self, monkeypatch, tmp_path, capsys):
        flag = str(tmp_path / "disabled")
        monkeypatch.setattr(inst_mod, "DISABLED_FLAG", flag)
        inst_mod.run_disable()
        assert os.path.exists(flag)
        assert "disabled" in capsys.readouterr().out

    def test_disable_idempotent(self, monkeypatch, tmp_path, capsys):
        flag = str(tmp_path / "disabled")
        monkeypatch.setattr(inst_mod, "DISABLED_FLAG", flag)
        inst_mod.run_disable()
        inst_mod.run_disable()  # must not raise
        assert os.path.exists(flag)

    def test_enable_removes_flag(self, monkeypatch, tmp_path, capsys):
        flag = str(tmp_path / "disabled")
        monkeypatch.setattr(inst_mod, "DISABLED_FLAG", flag)
        inst_mod.run_disable()
        inst_mod.run_enable()
        assert not os.path.exists(flag)
        assert "enabled" in capsys.readouterr().out

    def test_enable_noop_when_not_disabled(self, monkeypatch, tmp_path):
        flag = str(tmp_path / "disabled")
        monkeypatch.setattr(inst_mod, "DISABLED_FLAG", flag)
        inst_mod.run_enable()  # must not raise
        assert not os.path.exists(flag)


class TestSlashCommands:
    def test_install_creates_command_files(self, monkeypatch, tmp_path):
        cmds_dir = str(tmp_path / "commands")
        monkeypatch.setattr(inst_mod, "COMMANDS_DIR", cmds_dir)
        monkeypatch.setattr(inst_mod, "_QTE_OFF_CMD", str(tmp_path / "commands" / "qte-off.md"))
        monkeypatch.setattr(inst_mod, "_QTE_ON_CMD", str(tmp_path / "commands" / "qte-on.md"))
        monkeypatch.setattr(inst_mod, "_QTE_SOUND_CMD", str(tmp_path / "commands" / "qte-sound.md"))
        inst_mod.install_slash_commands()
        assert os.path.exists(inst_mod._QTE_OFF_CMD)
        assert os.path.exists(inst_mod._QTE_ON_CMD)
        assert os.path.exists(inst_mod._QTE_SOUND_CMD)

    def test_uninstall_removes_command_files(self, monkeypatch, tmp_path):
        cmds_dir = str(tmp_path / "commands")
        monkeypatch.setattr(inst_mod, "COMMANDS_DIR", cmds_dir)
        monkeypatch.setattr(inst_mod, "_QTE_OFF_CMD", str(tmp_path / "commands" / "qte-off.md"))
        monkeypatch.setattr(inst_mod, "_QTE_ON_CMD", str(tmp_path / "commands" / "qte-on.md"))
        monkeypatch.setattr(inst_mod, "_QTE_SOUND_CMD", str(tmp_path / "commands" / "qte-sound.md"))
        inst_mod.install_slash_commands()
        inst_mod.uninstall_slash_commands()
        assert not os.path.exists(inst_mod._QTE_OFF_CMD)
        assert not os.path.exists(inst_mod._QTE_ON_CMD)
        assert not os.path.exists(inst_mod._QTE_SOUND_CMD)

    def test_uninstall_noop_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(inst_mod, "_QTE_OFF_CMD", str(tmp_path / "qte-off.md"))
        monkeypatch.setattr(inst_mod, "_QTE_ON_CMD", str(tmp_path / "qte-on.md"))
        monkeypatch.setattr(inst_mod, "_QTE_SOUND_CMD", str(tmp_path / "qte-sound.md"))
        inst_mod.uninstall_slash_commands()  # must not raise


class TestLatestGithubTag:
    def test_returns_tag_on_success(self, monkeypatch):
        import urllib.request

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                return json.dumps({"tag_name": "v1.5.0"}).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
        assert _latest_github_tag() == "1.5.0"

    def test_returns_empty_on_network_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("fail")),
        )
        assert _latest_github_tag() == ""

    def test_returns_empty_on_missing_tag(self, monkeypatch):
        import urllib.request

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                return json.dumps({}).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
        assert _latest_github_tag() == ""


class TestEditable:
    def test_returns_path_for_editable_install(self, monkeypatch):
        fake_pkg = MagicMock()
        fake_pkg.read_text.return_value = json.dumps(
            {"dir_info": {"editable": True}, "url": "file:///home/user/myrepo"}
        )
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "distribution", lambda name: fake_pkg)
        assert _editable_repo_path() == "/home/user/myrepo"

    def test_returns_empty_for_non_editable(self, monkeypatch):
        fake_pkg = MagicMock()
        fake_pkg.read_text.return_value = json.dumps(
            {"dir_info": {"editable": False}, "url": "file:///home/user/myrepo"}
        )
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "distribution", lambda name: fake_pkg)
        assert _editable_repo_path() == ""

    def test_returns_empty_on_exception(self, monkeypatch):
        import importlib.metadata

        monkeypatch.setattr(
            importlib.metadata,
            "distribution",
            lambda name: (_ for _ in ()).throw(Exception("no pkg")),
        )
        assert _editable_repo_path() == ""


class TestRunUpdate:
    def test_already_up_to_date(self, monkeypatch, capsys):
        from claude_qte import __version__

        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: __version__)
        run_update()
        out = capsys.readouterr().out
        assert "up to date" in out

    def test_github_unreachable_exits(self, monkeypatch):
        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: "")
        with pytest.raises(SystemExit) as exc:
            run_update()
        assert exc.value.code == 1

    def test_editable_install_runs_git_pull(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: "9.9.9")
        monkeypatch.setattr(inst_mod, "_editable_repo_path", lambda: str(tmp_path))
        result = MagicMock()
        result.returncode = 0
        ran = []

        def _run(cmd, **kw):
            ran.append(cmd)
            return result

        monkeypatch.setattr(subprocess, "run", _run)
        run_update()
        assert any("git" in str(c) for c in ran)

    def test_editable_git_pull_failure_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: "9.9.9")
        monkeypatch.setattr(inst_mod, "_editable_repo_path", lambda: str(tmp_path))
        result = MagicMock()
        result.returncode = 1
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: result)
        with pytest.raises(SystemExit) as exc:
            run_update()
        assert exc.value.code == 1

    def test_pip_install_upgrade(self, monkeypatch, capsys):
        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: "9.9.9")
        monkeypatch.setattr(inst_mod, "_editable_repo_path", lambda: "")
        result = MagicMock()
        result.returncode = 0
        ran = []

        def _run(cmd, **kw):
            ran.append(cmd)
            return result

        monkeypatch.setattr(subprocess, "run", _run)
        run_update()
        assert any("pip" in str(c) for c in ran)

    def test_pip_install_failure_exits(self, monkeypatch):
        monkeypatch.setattr(inst_mod, "_latest_github_tag", lambda: "9.9.9")
        monkeypatch.setattr(inst_mod, "_editable_repo_path", lambda: "")
        result = MagicMock()
        result.returncode = 1
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: result)
        with pytest.raises(SystemExit) as exc:
            run_update()
        assert exc.value.code == 1


class TestInstallBinary:
    def test_frozen_binary_copies_to_target(self, monkeypatch, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        src = tmp_path / "claude-qte-src"
        src.write_text("binary")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(src))
        monkeypatch.setattr(inst_mod, "INSTALL_BIN_DIR", str(bin_dir))
        monkeypatch.setattr(inst_mod, "IS_MACOS", False)
        result = _install_binary()
        assert result == str(bin_dir / "claude-qte")
        assert os.path.exists(result)

    def test_non_frozen_invoker_path_returned(self, monkeypatch, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_bin = bin_dir / "claude-qte"
        fake_bin.write_text("#!/bin/sh")
        fake_bin.chmod(0o755)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(sys, "argv", [str(fake_bin)])
        monkeypatch.setattr(inst_mod, "INSTALL_BIN_DIR", str(bin_dir))
        result = _install_binary()
        assert result == str(fake_bin)

    def test_source_run_exits_with_2(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(sys, "argv", ["python"])
        monkeypatch.setattr(inst_mod, "INSTALL_BIN_DIR", str(tmp_path))
        with pytest.raises(SystemExit) as exc:
            _install_binary()
        assert exc.value.code == 2


class TestRemoveLegacyLaunchAgent:
    def test_returns_false_on_linux(self, monkeypatch):
        monkeypatch.setattr(inst_mod, "IS_MACOS", False)
        assert remove_legacy_launch_agent() is False

    def test_returns_false_when_plist_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(inst_mod, "IS_MACOS", True)
        monkeypatch.setattr(inst_mod, "LEGACY_PLIST_PATH", str(tmp_path / "missing.plist"))
        assert remove_legacy_launch_agent() is False

    def test_removes_plist_and_returns_true(self, monkeypatch, tmp_path, capsys):
        plist = tmp_path / "gate.plist"
        plist.write_text("<plist/>")
        monkeypatch.setattr(inst_mod, "IS_MACOS", True)
        monkeypatch.setattr(inst_mod, "LEGACY_PLIST_PATH", str(plist))
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=0))
        result = remove_legacy_launch_agent()
        assert result is True
        assert not plist.exists()
