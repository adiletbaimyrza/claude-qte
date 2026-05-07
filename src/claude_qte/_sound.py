"""Popup notification sound support.

Sounds are bundled in the package under ``sounds/``. The active sound is
stored as a name (without extension) in ``~/.config/claude-qte/sound``.
Playing is fire-and-forget via a background thread so it never blocks the TUI.
"""

import importlib.resources
import os
import shutil
import subprocess
import threading

_CONFIG_DIR = os.path.expanduser("~/.config/claude-qte")
_SOUND_FILE = os.path.join(_CONFIG_DIR, "sound")

DEFAULT_SOUND = "notification"
SOUND_OFF = "off"

SOUNDS: dict[str, str] = {
    "notification": "Default notification",
    "quack": "Quack",
    "augh": "Augh",
    "rizz": "Rizz",
    "gay_echo": "Gay echo",
    "fahhh": "Fahhh",
    "henta_ahh": "Henta ahh",
}


def is_muted() -> bool:
    """Return True if sound has been disabled."""
    try:
        with open(_SOUND_FILE, encoding="utf-8") as fh:
            return fh.read().strip() == SOUND_OFF
    except OSError:
        return False


def get_sound() -> str:
    """Return the configured sound name, or SOUND_OFF if muted, falling back to default."""
    try:
        with open(_SOUND_FILE, encoding="utf-8") as fh:
            name = fh.read().strip()
        if name == SOUND_OFF or name in SOUNDS:
            return name
    except OSError:
        pass
    return DEFAULT_SOUND


def set_sound(name: str) -> bool:
    """Persist *name* as the active sound. Returns False if unknown."""
    if name not in SOUNDS:
        return False
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_SOUND_FILE, "w", encoding="utf-8") as fh:
        fh.write(name)
    return True


def mute_sound() -> None:
    """Disable the notification sound."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_SOUND_FILE, "w", encoding="utf-8") as fh:
        fh.write(SOUND_OFF)


def unmute_sound() -> None:
    """Re-enable the notification sound (restores default)."""
    import contextlib

    with contextlib.suppress(FileNotFoundError):
        os.unlink(_SOUND_FILE)


def _sound_path(name: str) -> str | None:
    """Return an absolute path to the bundled mp3 for *name*, or None."""
    try:
        pkg = importlib.resources.files("claude_qte") / "sounds" / f"{name}.mp3"
        # importlib.resources may return a Path or a traversable; resolve to str.
        with importlib.resources.as_file(pkg) as path:
            return str(path)
    except (FileNotFoundError, TypeError, AttributeError):
        return None


def _find_player() -> list[str] | None:
    """Return a command prefix that can play an mp3, or None."""
    for player in ("paplay", "pw-play", "aplay", "mpg123", "ffplay"):
        if shutil.which(player):
            if player == "ffplay":
                return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
            return [player]
    return None


def play_notification() -> None:
    """Play the configured notification sound in a background thread."""
    name = get_sound()
    if name == SOUND_OFF:
        return
    path = _sound_path(name)
    if not path:
        return
    player = _find_player()
    if not player:
        return

    def _play() -> None:
        import contextlib

        with contextlib.suppress(Exception):
            subprocess.run(
                [*player, path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )

    threading.Thread(target=_play, daemon=True).start()
