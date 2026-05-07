import json
import curses
from unittest.mock import MagicMock, patch
from claude_qte.tui import _parse_question, HAS_PYGMENTS

def test_parse_question_plain_text():
    label, lines, is_diff = _parse_question("Hello world")
    assert label == "Tool use"
    assert lines == ["Hello world"]
    assert is_diff is False

def test_parse_question_diff():
    diff_data = {
        "__diff__": True,
        "path": "test.py",
        "diff": "--- test.py\n+++ test.py\n@@ -1,1 +1,1 @@\n-old\n+print('hello')\n"
    }
    raw = json.dumps(diff_data)
    
    # We need to mock curses.color_pair because it requires a live curses session
    with patch("curses.color_pair", side_effect=lambda x: x):
        label, lines, is_diff = _parse_question(raw)
    
    assert label == "test.py"
    assert is_diff is True
    
    # Check if lines are segmented
    # Line 0: --- test.py (meta)
    # Line 1: +++ test.py (meta)
    # Line 2: @@ -1,1 +1,1 @@ (hunk)
    # Line 3: -old (del)
    # Line 4: +print('hello') (add)
    
    assert len(lines) == 5
    
    # Check Line 4 (+print('hello'))
    # If HAS_PYGMENTS is True, it should be segmented
    plus_line = lines[4]
    assert plus_line[0][0] == "+"
    
    if HAS_PYGMENTS:
        # print('hello') should be lexed
        # segments: ['+', 'print', '(', "'hello'", ')']
        # plus prefix + at least one more segment
        assert len(plus_line) > 2
        texts = "".join(seg[0] for seg in plus_line)
        assert texts == "+print('hello')"
    else:
        assert len(plus_line) == 2
        assert plus_line[1][0] == "print('hello')"

def test_parse_question_diff_no_pygments():
    diff_data = {
        "__diff__": True,
        "path": "test.py",
        "diff": "+new line\n"
    }
    raw = json.dumps(diff_data)
    
    with patch("claude_qte.tui.HAS_PYGMENTS", False):
        with patch("curses.color_pair", side_effect=lambda x: x):
            label, lines, is_diff = _parse_question(raw)
            
    assert is_diff is True
    assert lines[0][0] == ("+", 6) # DIFF_ADD_PAIR = 6
    assert lines[0][1][0] == "new line"
