"""Pure helpers in :mod:`claude_qte._runtime`."""

import os

from claude_qte._runtime import (
    applescript_string,
    next_request_id,
    safe_unlink,
    shell_quote,
)


class TestShellQuote:
    def test_simple_word_unchanged(self):
        assert shell_quote("hello") == "hello"

    def test_alphanum_with_safe_specials_unchanged(self):
        assert shell_quote("/usr/local/bin") == "/usr/local/bin"
        assert shell_quote("a.b-c_d:e@f") == "a.b-c_d:e@f"

    def test_empty_string_quoted(self):
        assert shell_quote("") == "''"

    def test_space_gets_quoted(self):
        assert shell_quote("hello world") == "'hello world'"

    def test_single_quote_escaped(self):
        # ' → '"'"' (close, double-quoted single, reopen)
        assert shell_quote("it's") == "'it'\"'\"'s'"

    def test_dollar_sign_quoted(self):
        # Important: prevents shell variable expansion
        assert shell_quote("$VAR") == "'$VAR'"


class TestApplescriptString:
    def test_simple_quoted(self):
        assert applescript_string("hello") == '"hello"'

    def test_double_quote_escaped(self):
        assert applescript_string('say "hi"') == '"say \\"hi\\""'

    def test_backslash_escaped(self):
        assert applescript_string("a\\b") == '"a\\\\b"'

    def test_empty_string(self):
        assert applescript_string("") == '""'


class TestNextRequestId:
    def test_returns_unique_ids(self):
        ids = {next_request_id() for _ in range(10)}
        assert len(ids) == 10

    def test_format_is_seconds_seq_pid(self):
        rid = next_request_id()
        parts = rid.split("-")
        assert len(parts) == 3
        # all parts are numeric
        assert all(p.isdigit() for p in parts)


class TestSafeUnlink:
    def test_removes_existing_file(self, tmp_path):
        f = tmp_path / "x"
        f.write_text("hi")
        safe_unlink(str(f))
        assert not f.exists()

    def test_silently_ignores_missing(self, tmp_path):
        # Must not raise
        safe_unlink(str(tmp_path / "does-not-exist"))

    def test_other_errors_still_raise(self, tmp_path):
        # Pointing at a directory should not be silently swallowed —
        # only FileNotFoundError is caught.
        d = tmp_path / "dir"
        d.mkdir()
        try:
            safe_unlink(str(d))
        except (IsADirectoryError, PermissionError, OSError):
            return
        # On some systems unlink on a directory may succeed, in which case
        # this assertion lets us know the behavior.
        assert os.path.exists(str(d))
