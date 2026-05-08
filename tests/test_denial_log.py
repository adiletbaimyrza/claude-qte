"""Tests for :mod:`claude_qte.denial_log`."""

import json
import os
from pathlib import Path

import claude_qte.denial_log as dl


class TestLogDenial:
    def test_creates_file_and_appends_entry(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "rm -rf /"}, "too dangerous", "/home/x", path=log)
        lines = Path(log).read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tool"] == "Bash"
        assert entry["reason"] == "too dangerous"
        assert entry["command"] == "rm -rf /"
        assert entry["cwd"] == "/home/x"
        assert isinstance(entry["ts"], int)

    def test_appends_multiple_entries(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "ls"}, "reason1", path=log)
        dl.log_denial("Edit", {"file_path": "/etc/passwd"}, "reason2", path=log)
        lines = Path(log).read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["tool"] == "Bash"
        assert json.loads(lines[1])["tool"] == "Edit"

    def test_bash_includes_command(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "git push --force"}, "no force push", path=log)
        entry = json.loads(Path(log).read_text())
        assert entry["command"] == "git push --force"
        assert "file_path" not in entry

    def test_edit_includes_file_path(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Edit", {"file_path": "/etc/hosts"}, "sensitive file", path=log)
        entry = json.loads(Path(log).read_text())
        assert entry["file_path"] == "/etc/hosts"
        assert "command" not in entry

    def test_write_includes_file_path(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Write", {"file_path": "/tmp/out.txt"}, "bad path", path=log)
        entry = json.loads(Path(log).read_text())
        assert entry["file_path"] == "/tmp/out.txt"

    def test_notebook_edit_prefers_notebook_path(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial(
            "NotebookEdit",
            {"notebook_path": "/nb.ipynb", "file_path": "/wrong"},
            "reason",
            path=log,
        )
        entry = json.loads(Path(log).read_text())
        assert entry["file_path"] == "/nb.ipynb"

    def test_notebook_edit_falls_back_to_file_path(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("NotebookEdit", {"file_path": "/nb.ipynb"}, "reason", path=log)
        entry = json.loads(Path(log).read_text())
        assert entry["file_path"] == "/nb.ipynb"

    def test_omits_cwd_when_empty(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "ls"}, "reason", cwd="", path=log)
        entry = json.loads(Path(log).read_text())
        assert "cwd" not in entry

    def test_unknown_tool_omits_detail_fields(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Mystery", {"foo": "bar"}, "reason", path=log)
        entry = json.loads(Path(log).read_text())
        assert "command" not in entry
        assert "file_path" not in entry

    def test_oserror_does_not_raise(self, tmp_path):
        # A path inside a non-existent nested directory we can't create is not
        # easy to engineer reliably, so test by pointing at a directory as the log file.
        log = str(tmp_path)  # tmp_path itself is a directory, not a file
        # Should not raise — logging must never break the hook decision.
        dl.log_denial("Bash", {"command": "ls"}, "reason", path=log)

    def test_empty_command_not_included(self, tmp_path):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": ""}, "reason", path=log)
        entry = json.loads(Path(log).read_text())
        assert "command" not in entry


class TestPrintDenials:
    def test_no_file_prints_message(self, tmp_path, capsys):
        dl.print_denials(path=str(tmp_path / "missing.log"))
        assert "No denials" in capsys.readouterr().out

    def test_empty_file_prints_message(self, tmp_path, capsys):
        log = tmp_path / "denials.log"
        log.write_text("")
        dl.print_denials(path=str(log))
        assert "No denials" in capsys.readouterr().out

    def test_prints_entries(self, tmp_path, capsys):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "rm -rf /"}, "dangerous", path=log)
        dl.print_denials(path=log)
        out = capsys.readouterr().out
        assert "Bash" in out
        assert "rm -rf /" in out
        assert "dangerous" in out

    def test_last_n_limits_output(self, tmp_path, capsys):
        log = str(tmp_path / "denials.log")
        for i in range(5):
            dl.log_denial("Bash", {"command": f"cmd{i}"}, f"reason{i}", path=log)
        dl.print_denials(path=log, last=2)
        out = capsys.readouterr().out
        assert "cmd4" in out
        assert "cmd3" in out
        assert "cmd0" not in out

    def test_truncates_long_detail(self, tmp_path, capsys):
        log = str(tmp_path / "denials.log")
        dl.log_denial("Bash", {"command": "x" * 100}, "reason", path=log)
        dl.print_denials(path=log)
        out = capsys.readouterr().out
        assert "..." in out

    def test_skips_malformed_lines(self, tmp_path, capsys):
        log = tmp_path / "denials.log"
        log.write_text("not json\n" + json.dumps({"ts": 0, "tool": "Bash", "reason": "r"}) + "\n")
        dl.print_denials(path=str(log))
        out = capsys.readouterr().out
        assert "Bash" in out


class TestHookIntegration:
    """Verify hook.run_hook calls log_denial on a gate denial."""

    def test_denial_is_logged(self, monkeypatch, tmp_path, capsys):
        import io

        import claude_qte.hook as hook_mod

        log_path = str(tmp_path / "denials.log")
        monkeypatch.setattr(hook_mod, "DISABLED_FLAG", str(tmp_path / "disabled"))
        monkeypatch.setattr(hook_mod, "_is_permitted", lambda *a: False)
        monkeypatch.setattr(hook_mod, "_ensure_gate", lambda ppid: 9999)
        monkeypatch.setattr(hook_mod, "is_gate_self_call", lambda event, port: False)
        monkeypatch.setattr(hook_mod, "user_is_present", lambda: False)
        monkeypatch.setattr(
            hook_mod, "call_gate", lambda port, q: {"approved": False, "answer": "wrong tool"}
        )
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(
                json.dumps({"tool_name": "Bash", "tool_input": {"command": "bad cmd"}, "cwd": "/x"})
            ),
        )
        # Capture log_denial calls by wrapping it
        logged = []

        def _capture_log(tool_name, tool_input, reason, cwd="", path=dl.DENIAL_LOG_PATH):
            dl.log_denial(tool_name, tool_input, reason, cwd, path=str(tmp_path / "denials.log"))
            logged.append((tool_name, tool_input, reason))

        monkeypatch.setattr(hook_mod, "log_denial", _capture_log)

        hook_mod.run_hook()

        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

        assert logged == [("Bash", {"command": "bad cmd"}, "wrong tool")]
        assert os.path.exists(log_path)
        entry = json.loads(Path(log_path).read_text())
        assert entry["tool"] == "Bash"
        assert entry["command"] == "bad cmd"
        assert entry["reason"] == "wrong tool"

    def test_approval_is_not_logged(self, monkeypatch, tmp_path, capsys):
        import io

        import claude_qte.hook as hook_mod

        monkeypatch.setattr(hook_mod, "DISABLED_FLAG", str(tmp_path / "disabled"))
        monkeypatch.setattr(hook_mod, "_is_permitted", lambda *a: False)
        monkeypatch.setattr(hook_mod, "_ensure_gate", lambda ppid: 9999)
        monkeypatch.setattr(hook_mod, "is_gate_self_call", lambda event, port: False)
        monkeypatch.setattr(hook_mod, "user_is_present", lambda: False)
        monkeypatch.setattr(
            hook_mod, "call_gate", lambda port, q: {"approved": True, "answer": "looks fine"}
        )
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})),
        )

        logged = []
        monkeypatch.setattr(hook_mod, "log_denial", lambda *a, **kw: logged.append(a))

        hook_mod.run_hook()

        assert logged == []
