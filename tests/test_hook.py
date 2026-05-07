"""Pure logic in :mod:`claude_qte.hook` — no subprocess, no I/O."""

import json

import claude_qte.hook as hook_mod
from claude_qte.hook import describe_tool, emit_decision, is_gate_self_call


class TestDescribeTool:
    def test_bash_with_description(self):
        out = describe_tool("Bash", {"command": "ls", "description": "list files"})
        assert "Bash — list files" in out
        assert "$ ls" in out

    def test_bash_without_description(self):
        out = describe_tool("Bash", {"command": "ls"})
        assert out.startswith("Bash\n\n$ ls")

    def test_edit(self):
        assert describe_tool("Edit", {"file_path": "/x/y.py"}) == "Edit /x/y.py"

    def test_write_includes_size(self):
        out = describe_tool("Write", {"file_path": "/a", "content": "abcde"})
        assert "Write /a" in out
        assert "(5 chars)" in out

    def test_notebook_edit_prefers_notebook_path(self):
        out = describe_tool(
            "NotebookEdit",
            {"notebook_path": "/n.ipynb", "file_path": "/wrong"},
        )
        assert out == "NotebookEdit /n.ipynb"

    def test_unknown_tool_dumps_input(self):
        out = describe_tool("Mystery", {"foo": 1})
        assert out.startswith("Mystery\n\n")
        assert json.loads(out.split("\n\n", 1)[1]) == {"foo": 1}

    def test_unknown_tool_truncates_long_input(self):
        out = describe_tool("X", {"big": "a" * 5000})
        assert out.endswith("…")
        assert len(out) < 1000


class TestIsGateSelfCall:
    def test_curl_to_localhost_ask(self):
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "curl http://localhost:9999/ask?q=hi"},
        }
        assert is_gate_self_call(event, 9999) is True

    def test_curl_to_127_0_0_1_ping(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "curl 127.0.0.1:9999/ping"}}
        assert is_gate_self_call(event, 9999) is True

    def test_wrong_port(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "curl localhost:9998/ask"}}
        assert is_gate_self_call(event, 9999) is False

    def test_non_bash_tool(self):
        event = {"tool_name": "Edit", "tool_input": {"file_path": "/x"}}
        assert is_gate_self_call(event, 9999) is False

    def test_empty_event(self):
        assert is_gate_self_call({}, 9999) is False


class TestPingGate:
    def test_returns_true_on_ok_response(self, monkeypatch):
        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
        assert hook_mod._ping_gate(9999) is True

    def test_returns_false_on_connection_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        def _raise(*a, **kw):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        assert hook_mod._ping_gate(9999) is False


class TestEnsureGate:
    def test_uses_env_var_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_QTE_PORT", "8888")
        monkeypatch.setattr(hook_mod, "_ping_gate", lambda port: True)
        monkeypatch.setattr(hook_mod, "TMP_DIR", str(tmp_path))
        result = hook_mod._ensure_gate(ppid=9999)
        assert result == 8888

    def test_uses_port_file_when_valid(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_QTE_PORT", raising=False)
        port_file = tmp_path / "gate-1234.port"
        port_file.write_text("7777")
        monkeypatch.setattr(hook_mod, "TMP_DIR", str(tmp_path))
        monkeypatch.setattr(hook_mod, "_ping_gate", lambda port: True)
        result = hook_mod._ensure_gate(ppid=1234)
        assert result == 7777

    def test_spawns_when_port_file_stale(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_QTE_PORT", raising=False)
        port_file = tmp_path / "gate-1234.port"
        port_file.write_text("7777")
        monkeypatch.setattr(hook_mod, "TMP_DIR", str(tmp_path))
        # ping always fails → stale
        monkeypatch.setattr(hook_mod, "_ping_gate", lambda port: False)
        spawned = {}
        monkeypatch.setattr(
            hook_mod,
            "_spawn_gate",
            lambda port, ppid: spawned.update({"port": port, "ppid": ppid}) or True,
        )
        monkeypatch.setattr(hook_mod, "pick_free_port", lambda: 6666)
        result = hook_mod._ensure_gate(ppid=1234)
        assert result == 6666
        assert spawned["ppid"] == 1234

    def test_spawns_when_no_port_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_QTE_PORT", raising=False)
        monkeypatch.setattr(hook_mod, "TMP_DIR", str(tmp_path))
        monkeypatch.setattr(hook_mod, "_ping_gate", lambda port: False)
        monkeypatch.setattr(hook_mod, "_spawn_gate", lambda port, ppid: True)
        monkeypatch.setattr(hook_mod, "pick_free_port", lambda: 5555)
        result = hook_mod._ensure_gate(ppid=9999)
        assert result == 5555

    def test_returns_none_when_spawn_fails(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CLAUDE_QTE_PORT", raising=False)
        monkeypatch.setattr(hook_mod, "TMP_DIR", str(tmp_path))
        monkeypatch.setattr(hook_mod, "_ping_gate", lambda port: False)
        monkeypatch.setattr(hook_mod, "_spawn_gate", lambda port, ppid: False)
        monkeypatch.setattr(hook_mod, "pick_free_port", lambda: 4444)
        result = hook_mod._ensure_gate(ppid=9999)
        assert result is None


class TestDisabledFlag:
    def test_disabled_flag_causes_ask(self, monkeypatch, tmp_path, capsys):
        flag = str(tmp_path / "disabled")
        open(flag, "w").close()
        monkeypatch.setattr(hook_mod, "DISABLED_FLAG", flag)

        import io

        monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "Bash", "tool_input": {}}'))
        hook_mod.run_hook()
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_no_flag_does_not_short_circuit(self, monkeypatch, tmp_path):
        flag = str(tmp_path / "disabled")
        monkeypatch.setattr(hook_mod, "DISABLED_FLAG", flag)
        # Flag absent — should NOT short-circuit (reaches presence check).
        assert not __import__("os").path.exists(flag)


class TestEmitDecision:
    def test_allow_without_reason(self, capsys):
        emit_decision("allow")
        out = json.loads(capsys.readouterr().out)
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    def test_deny_with_reason(self, capsys):
        emit_decision("deny", "user said no")
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == "user said no"

    def test_ask_omits_reason_when_blank(self, capsys):
        emit_decision("ask", "")
        out = json.loads(capsys.readouterr().out)
        assert "permissionDecisionReason" not in out["hookSpecificOutput"]
