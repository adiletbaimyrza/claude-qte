"""Tests for claude_qte.installer — patch_claude_md / unpatch_claude_md."""

import os

import claude_qte.installer as inst_mod


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
        inst_mod.install_slash_commands()
        assert os.path.exists(inst_mod._QTE_OFF_CMD)
        assert os.path.exists(inst_mod._QTE_ON_CMD)

    def test_uninstall_removes_command_files(self, monkeypatch, tmp_path):
        cmds_dir = str(tmp_path / "commands")
        monkeypatch.setattr(inst_mod, "COMMANDS_DIR", cmds_dir)
        monkeypatch.setattr(inst_mod, "_QTE_OFF_CMD", str(tmp_path / "commands" / "qte-off.md"))
        monkeypatch.setattr(inst_mod, "_QTE_ON_CMD", str(tmp_path / "commands" / "qte-on.md"))
        inst_mod.install_slash_commands()
        inst_mod.uninstall_slash_commands()
        assert not os.path.exists(inst_mod._QTE_OFF_CMD)
        assert not os.path.exists(inst_mod._QTE_ON_CMD)

    def test_uninstall_noop_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(inst_mod, "_QTE_OFF_CMD", str(tmp_path / "qte-off.md"))
        monkeypatch.setattr(inst_mod, "_QTE_ON_CMD", str(tmp_path / "qte-on.md"))
        inst_mod.uninstall_slash_commands()  # must not raise
