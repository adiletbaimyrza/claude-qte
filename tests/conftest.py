import pytest


@pytest.fixture
def settings_path(tmp_path):
    """A throwaway settings.json path under pytest's tmp_path."""
    return str(tmp_path / "settings.json")
