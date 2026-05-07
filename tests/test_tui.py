import curses
import json
from unittest.mock import MagicMock, patch

from claude_qte.tui import (
    HAS_PYGMENTS,
    TEXT_PAIR,
    _get_token_pair,
    _parse_question,
    _safe_addstr,
    _wrap,
)


def test_parse_question_plain_text():
    label, lines, is_diff = _parse_question("Hello world")
    assert label == "Tool use"
    assert lines == ["Hello world"]
    assert is_diff is False


def test_parse_question_diff():
    diff_data = {
        "__diff__": True,
        "path": "test.py",
        "diff": "--- test.py\n+++ test.py\n@@ -1,1 +1,1 @@\n-old\n+print('hello')\n",
    }
    raw = json.dumps(diff_data)

    with patch("curses.color_pair", side_effect=lambda x: x):
        label, lines, is_diff = _parse_question(raw)

    assert label == "test.py"
    assert is_diff is True
    assert len(lines) == 5

    plus_line = lines[4]
    assert plus_line[0][0] == "+"

    if HAS_PYGMENTS:
        assert len(plus_line) > 2
        texts = "".join(seg[0] for seg in plus_line)
        assert texts == "+print('hello')"
    else:
        assert len(plus_line) == 2
        assert plus_line[1][0] == "print('hello')"


def test_parse_question_diff_no_pygments():
    diff_data = {"__diff__": True, "path": "test.py", "diff": "+new line\n"}
    raw = json.dumps(diff_data)

    with (
        patch("claude_qte.tui.HAS_PYGMENTS", False),
        patch("curses.color_pair", side_effect=lambda x: x),
    ):
        _label, lines, is_diff = _parse_question(raw)

    assert is_diff is True
    assert lines[0][0] == ("+", 6)  # DIFF_ADD_PAIR = 6
    assert lines[0][1][0] == "new line"


class TestWrap:
    def test_empty_string_returns_empty_segment(self):
        assert _wrap("", 80) == [""]

    def test_short_line_returned_as_is(self):
        assert _wrap("hello", 80) == ["hello"]

    def test_long_line_wrapped(self):
        result = _wrap("a" * 200, 80)
        assert len(result) > 1
        for part in result:
            assert len(part) <= 80

    def test_multiline_preserves_blank_lines(self):
        result = _wrap("first\n\nthird", 80)
        assert "" in result

    def test_width_one_returns_text(self):
        result = _wrap("hello", 1)
        assert result == ["hello"]

    def test_multiline_wraps_each_paragraph(self):
        result = _wrap("a" * 100 + "\n" + "b" * 100, 50)
        assert len(result) >= 4


class TestSafeAddstr:
    def _make_stdscr(self, h=24, w=80):
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (h, w)
        return stdscr

    def test_normal_call(self):
        stdscr = self._make_stdscr()
        _safe_addstr(stdscr, 5, 10, "hello", 0)
        stdscr.addnstr.assert_called_once()

    def test_out_of_bounds_y_is_noop(self):
        stdscr = self._make_stdscr(h=10)
        _safe_addstr(stdscr, 10, 0, "hello")
        stdscr.addnstr.assert_not_called()

    def test_out_of_bounds_x_is_noop(self):
        stdscr = self._make_stdscr(w=10)
        _safe_addstr(stdscr, 0, 10, "hello")
        stdscr.addnstr.assert_not_called()

    def test_negative_y_is_noop(self):
        stdscr = self._make_stdscr()
        _safe_addstr(stdscr, -1, 0, "hello")
        stdscr.addnstr.assert_not_called()

    def test_curses_error_suppressed(self):
        stdscr = self._make_stdscr()
        stdscr.addnstr.side_effect = curses.error("test error")
        _safe_addstr(stdscr, 0, 0, "hello")  # must not raise


class TestGetTokenPair:
    def test_returns_text_pair_without_pygments(self):
        with patch("claude_qte.tui.HAS_PYGMENTS", False):
            result = _get_token_pair(None, "normal")
        assert result == TEXT_PAIR

    def test_returns_valid_pair_with_pygments(self):
        with patch("claude_qte.tui.HAS_PYGMENTS", True):
            try:
                from pygments.token import Token

                result = _get_token_pair(Token.Text, "normal")
                assert isinstance(result, int)
                result_add = _get_token_pair(Token.Text, "add")
                assert isinstance(result_add, int)
                result_del = _get_token_pair(Token.Text, "del")
                assert isinstance(result_del, int)
            except ImportError:
                pass


class TestParseQuestionEdgeCases:
    def test_diff_with_hunk_line(self):
        diff_data = {"__diff__": True, "path": "x.py", "diff": "@@ -1,1 +1,1 @@\n"}
        with patch("curses.color_pair", side_effect=lambda x: x):
            label, lines, is_diff = _parse_question(json.dumps(diff_data))
        assert is_diff is True
        assert any("@@" in seg[0] for line in lines for seg in line)

    def test_diff_with_context_line(self):
        diff_data = {"__diff__": True, "path": "x.py", "diff": " unchanged line\n"}
        with patch("curses.color_pair", side_effect=lambda x: x):
            label, lines, is_diff = _parse_question(json.dumps(diff_data))
        assert is_diff is True

    def test_diff_with_meta_lines(self):
        diff_data = {"__diff__": True, "path": "x.py", "diff": "--- a/x.py\n+++ b/x.py\n"}
        with patch("curses.color_pair", side_effect=lambda x: x):
            label, lines, is_diff = _parse_question(json.dumps(diff_data))
        assert is_diff is True

    def test_invalid_json_returns_plain(self):
        label, lines, is_diff = _parse_question("not json {{{")
        assert label == "Tool use"
        assert is_diff is False

    def test_multiline_plain_text(self):
        label, lines, is_diff = _parse_question("line1\nline2\nline3")
        assert is_diff is False
        assert lines == ["line1", "line2", "line3"]
