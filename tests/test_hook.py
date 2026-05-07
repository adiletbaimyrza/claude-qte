"""Pure logic in :mod:`claude_qte.hook` — no subprocess, no I/O."""

import json

from claude_qte.hook import describe_tool, is_gate_self_call


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
        event = {"tool_name": "Bash",
                 "tool_input": {"command": "curl http://localhost:9999/ask?q=hi"}}
        assert is_gate_self_call(event, 9999) is True

    def test_curl_to_127_0_0_1_ping(self):
        event = {"tool_name": "Bash",
                 "tool_input": {"command": "curl 127.0.0.1:9999/ping"}}
        assert is_gate_self_call(event, 9999) is True

    def test_wrong_port(self):
        event = {"tool_name": "Bash",
                 "tool_input": {"command": "curl localhost:9998/ask"}}
        assert is_gate_self_call(event, 9999) is False

    def test_non_bash_tool(self):
        event = {"tool_name": "Edit", "tool_input": {"file_path": "/x"}}
        assert is_gate_self_call(event, 9999) is False

    def test_empty_event(self):
        assert is_gate_self_call({}, 9999) is False
