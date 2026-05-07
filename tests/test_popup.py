"""Pure helpers in :mod:`claude_qte.popup` — no AppleScript, no curses."""

from claude_qte.popup import (
    MAX_COLS,
    MAX_ROWS,
    MIN_COLS,
    MIN_ROWS,
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
        assert cols == MAX_COLS  # clamped

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
