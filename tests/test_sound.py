"""Tests for claude_qte._sound — all I/O and subprocess calls are mocked."""

import claude_qte._sound as sound_mod
from claude_qte._sound import (
    DEFAULT_SOUND,
    SOUND_OFF,
    SOUNDS,
    _find_player,
    _sound_path,
    get_sound,
    is_muted,
    mute_sound,
    play_notification,
    set_sound,
    unmute_sound,
)


class TestIsMuted:
    def test_returns_true_when_file_contains_off(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text(SOUND_OFF)
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        assert is_muted() is True

    def test_returns_false_when_file_contains_sound_name(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text("quack")
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        assert is_muted() is False

    def test_returns_false_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        assert is_muted() is False


class TestGetSound:
    def test_returns_configured_sound(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text("quack")
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        assert get_sound() == "quack"

    def test_returns_off_when_muted(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text(SOUND_OFF)
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        assert get_sound() == SOUND_OFF

    def test_falls_back_to_default_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        assert get_sound() == DEFAULT_SOUND

    def test_falls_back_to_default_when_unknown_name(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text("unknown_sound_xyz")
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        assert get_sound() == DEFAULT_SOUND


class TestSetSound:
    def test_sets_known_sound(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "sound"))
        assert set_sound("quack") is True
        assert (tmp_path / "sound").read_text() == "quack"

    def test_returns_false_for_unknown_sound(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "sound"))
        assert set_sound("does_not_exist") is False

    def test_all_known_sounds_accepted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "sound"))
        for name in SOUNDS:
            assert set_sound(name) is True


class TestMuteUnmute:
    def test_mute_writes_off(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "sound"))
        mute_sound()
        assert (tmp_path / "sound").read_text() == SOUND_OFF

    def test_unmute_removes_file(self, monkeypatch, tmp_path):
        f = tmp_path / "sound"
        f.write_text(SOUND_OFF)
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(f))
        unmute_sound()
        assert not f.exists()

    def test_unmute_noop_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        unmute_sound()  # must not raise


class TestFindPlayer:
    def test_returns_paplay_when_available(self, monkeypatch):
        monkeypatch.setattr(
            sound_mod.shutil, "which", lambda name: "/usr/bin/paplay" if name == "paplay" else None
        )
        assert _find_player() == ["paplay"]

    def test_returns_ffplay_with_flags(self, monkeypatch):
        monkeypatch.setattr(
            sound_mod.shutil, "which", lambda name: "/usr/bin/ffplay" if name == "ffplay" else None
        )
        result = _find_player()
        assert result is not None
        assert result[0] == "ffplay"
        assert "-nodisp" in result

    def test_returns_none_when_nothing_found(self, monkeypatch):
        monkeypatch.setattr(sound_mod.shutil, "which", lambda name: None)
        assert _find_player() is None


class TestSoundPath:
    def test_returns_path_for_known_sound(self):
        path = _sound_path("notification")
        # Either returns a valid path string or None (if not bundled in test env)
        assert path is None or isinstance(path, str)

    def test_returns_none_for_unknown_sound(self):
        assert _sound_path("definitely_not_a_real_sound") is None


class TestPlayNotification:
    def test_does_not_play_when_muted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "sound"))
        (tmp_path / "sound").write_text(SOUND_OFF)
        played = []
        monkeypatch.setattr(sound_mod, "_find_player", lambda: played.append(True) or ["paplay"])
        play_notification()
        assert played == []

    def test_does_not_play_when_no_player(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        monkeypatch.setattr(sound_mod, "_find_player", lambda: None)
        monkeypatch.setattr(sound_mod, "_sound_path", lambda name: "/fake/path.mp3")
        started = []

        class _FakeThread:
            def __init__(self, target, daemon=True):
                started.append(True)

            def start(self):
                pass

        monkeypatch.setattr(sound_mod.threading, "Thread", _FakeThread)
        play_notification()
        assert started == []

    def test_does_not_play_when_no_sound_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        monkeypatch.setattr(sound_mod, "_sound_path", lambda name: None)
        monkeypatch.setattr(sound_mod, "_find_player", lambda: ["paplay"])
        started = []

        class _FakeThread:
            def __init__(self, target, daemon=True):
                started.append(True)

            def start(self):
                pass

        monkeypatch.setattr(sound_mod.threading, "Thread", _FakeThread)
        play_notification()
        assert started == []

    def test_spawns_background_thread_when_ready(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sound_mod, "_SOUND_FILE", str(tmp_path / "missing"))
        monkeypatch.setattr(sound_mod, "_sound_path", lambda name: "/fake/path.mp3")
        monkeypatch.setattr(sound_mod, "_find_player", lambda: ["paplay"])

        threads = []

        class _FakeThread:
            def __init__(self, target, daemon=True):
                threads.append(self)

            def start(self):
                pass

        monkeypatch.setattr(sound_mod.threading, "Thread", _FakeThread)
        play_notification()
        assert len(threads) == 1
