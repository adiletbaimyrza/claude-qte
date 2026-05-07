"""``claude-qte install`` / ``uninstall``.

Drops the binary at ``~/.local/bin/claude-qte``, registers the PreToolUse
hook in ``~/.claude/settings.json``, and (for upgrades) cleans up the
always-on LaunchAgent that 0.1.x installed.
"""

import os
import platform
import shutil
import subprocess
import sys

from claude_qte import settings as settings_mod
from claude_qte.settings import SETTINGS_PATH

INSTALL_BIN_DIR = os.path.expanduser("~/.local/bin")
INSTALL_BIN_NAME = "claude-qte"

# 0.1.x leftover — installed an always-on background daemon. We boot it out
# during install/uninstall so upgrades don't leave a zombie running.
LEGACY_PLIST_LABEL = "com.claudeqte.gate"
LEGACY_PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LEGACY_PLIST_LABEL}.plist")


def run_install() -> None:
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte install is macOS-only.\n")
        sys.exit(2)

    bin_path = _install_binary()
    legacy_removed = remove_legacy_launch_agent()
    settings_mod.patch_for_hook(bin_path)

    legacy_note = ""
    if legacy_removed:
        legacy_note = "\n  Migrated from 0.1.x: the old always-on LaunchAgent has been removed.\n"

    print(f"""
  claude-qte installed.

  • Binary:  {bin_path}
  • Hook in: {SETTINGS_PATH}
{legacy_note}
  Add this to your shell profile (e.g. ~/.zshrc) so the gate runs only
  while you're in a Claude Code session:

      alias claude='{bin_path} run claude'

  Open a new terminal, run `claude`, and the gate will start with it and
  exit when you leave. When you wander off and Claude needs permission,
  the QTE popup will appear.
""")
    if INSTALL_BIN_DIR not in os.environ.get("PATH", "").split(":"):
        print(f"  Note: add {INSTALL_BIN_DIR} to your PATH to run `claude-qte` directly.\n")


def run_uninstall() -> None:
    if platform.system() != "Darwin":
        sys.stderr.write("claude-qte uninstall is macOS-only.\n")
        sys.exit(2)

    if remove_legacy_launch_agent():
        pass  # message already printed

    if settings_mod.unpatch_hook():
        print(f"  Removed claude-qte hook from {SETTINGS_PATH}")

    bin_path = os.path.join(INSTALL_BIN_DIR, INSTALL_BIN_NAME)
    if os.path.exists(bin_path):
        os.unlink(bin_path)
        print(f"  Removed {bin_path}")

    print("\n  claude-qte uninstalled.\n")
    print(
        "  Don't forget to remove the `alias claude=...` line from your\n"
        "  shell profile if you added one.\n"
    )


def _install_binary() -> str:
    """Place the running binary at the canonical install path.

    Supports two cases:
      1. PyInstaller-built single binary → copy ``sys.executable`` to target.
      2. ``pip install``-d console script → it's already at the right path,
         so we just chmod and move on.
    Source/dev runs (``python -m claude_qte install``) error out.
    """
    target = os.path.join(INSTALL_BIN_DIR, INSTALL_BIN_NAME)

    if getattr(sys, "frozen", False):
        os.makedirs(INSTALL_BIN_DIR, exist_ok=True)
        src = sys.executable
        if os.path.realpath(src) != os.path.realpath(target):
            shutil.copy2(src, target)
        os.chmod(target, 0o755)
        # Strip Gatekeeper quarantine so the binary runs without "are you sure?".
        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return target

    invoker = os.path.realpath(sys.argv[0]) if sys.argv else ""
    if invoker.endswith(INSTALL_BIN_NAME) and os.access(invoker, os.X_OK):
        return invoker

    sys.stderr.write(
        "claude-qte install requires the PyInstaller binary or a `pip install`-d entry "
        "point.\n"
        "Running directly from source isn't supported. Try:\n\n"
        "    pip install .\n"
        "    claude-qte install\n"
    )
    sys.exit(2)


def remove_legacy_launch_agent() -> bool:
    """0.1.x installed an always-on LaunchAgent. Remove it if present.

    Returns True if a legacy plist was found and removed.
    """
    if not os.path.exists(LEGACY_PLIST_PATH):
        return False
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", LEGACY_PLIST_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        os.unlink(LEGACY_PLIST_PATH)
    except OSError:
        return False
    print(f"  Removed legacy LaunchAgent {LEGACY_PLIST_PATH}")
    return True
