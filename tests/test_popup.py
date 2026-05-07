"""Tests for claude_qte.popup."""

import json
import os

from claude_qte.popup import (
    MAX_COLS,
    MAX_ROWS,
    MIN_COLS,
    MIN_ROWS,
    _display_text,
    compute_window_size,
)


class TestComputeWindowSize:
    def test_short_question_uses_min_dimensions(self):
        cols, rows = compute_window_size("ls")
        assert cols == MIN_COLS
        assert rows == MIN_ROWS

    def test_long_line_widens_window(self):
        question = "x" * 200
        cols, _ = compute_window_size(question)
        assert cols == MAX_COLS

    def test_many_lines_grows_height(self):
        question = "\n".join(["short"] * 30)
        _, rows = compute_window_size(question)
        assert rows > MIN_ROWS

    def test_height_clamped_to_max(self):
        question = "\n".join(["short"] * 200)
        _, rows = compute_window_size(question)
        assert rows == MAX_ROWS

    def test_width_within_bounds(self):
        for q in ["a", "a" * 50, "a" * 500, "\n".join(["x"] * 50)]:
            cols, rows = compute_window_size(q)
            assert MIN_COLS <= cols <= MAX_COLS
            assert MIN_ROWS <= rows <= MAX_ROWS

    def test_diff_payload_uses_diff_lines_for_sizing(self):
        long_line = "+" + "x" * 150
        payload = json.dumps({"__diff__": True, "path": "x.py", "diff": long_line})
        cols, _ = compute_window_size(payload)
        assert cols == MAX_COLS


class TestDisplayText:
    def test_plain_string_returned_as_is(self):
        assert _display_text("hello world") == "hello world"

    def test_diff_payload_returns_diff_body(self):
        payload = json.dumps({"__diff__": True, "path": "x.py", "diff": "--- a\n+++ b\n"})
        assert _display_text(payload) == "--- a\n+++ b\n"

    def test_non_diff_json_returned_as_is(self):
        payload = json.dumps({"foo": "bar"})
        assert _display_text(payload) == payload

    def test_invalid_json_returned_as_is(self):
        bad = "not {json"
        assert _display_text(bad) == bad


class TestPromptUser:
    def test_returns_timeout_when_answer_file_never_appears(self, monkeypatch, tmp_path):
        import time

        from claude_qte.popup import prompt_user

        monkeypatch.setattr("claude_qte.popup.TMP_DIR", str(tmp_path))
        monkeypatch.setattr("claude_qte.popup.ANSWER_TIMEOUT", 0)
        monkeypatch.setattr(time, "sleep", lambda _: None)
        monkeypatch.setattr("claude_qte.popup.spawn_terminal_window", lambda *a, **kw: "42")
        monkeypatch.setattr("claude_qte.popup.close_terminal_window", lambda *a, **kw: None)
        monkeypatch.setattr("claude_qte.popup.keep_window_on_top", lambda *a, **kw: None)
        monkeypatch.setattr("claude_qte.popup.play_notification", lambda: None)

        result = prompt_user("Do the thing?")
        assert result == {"approved": False, "text": "timeout"}

    def test_returns_answer_when_file_written(self, monkeypatch, tmp_path):
        import time

        from claude_qte import _runtime as rt
        from claude_qte.popup import prompt_user

        monkeypatch.setattr(rt, "TMP_DIR", str(tmp_path))
        monkeypatch.setattr(time, "sleep", lambda _: None)
        monkeypatch.setattr("claude_qte.popup.spawn_terminal_window", lambda *a, **kw: "42")
        monkeypatch.setattr("claude_qte.popup.close_terminal_window", lambda *a, **kw: None)
        monkeypatch.setattr("claude_qte.popup.keep_window_on_top", lambda *a, **kw: None)
        monkeypatch.setattr("claude_qte.popup.play_notification", lambda: None)

        real_exists = os.path.exists
        written = {"done": False}

        def _fake_exists(path):
            if path.endswith(".a") and not written["done"]:
                written["done"] = True
                with open(path, "w") as f:
                    json.dump({"approved": True, "text": "yes"}, f)
                return True
            return real_exists(path)

        monkeypatch.setattr(os.path, "exists", _fake_exists)

        result = prompt_user("Do the thing?")
        assert result["approved"] is True
        assert result["text"] == "yes"
