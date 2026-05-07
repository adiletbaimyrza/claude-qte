"""``claude-qte install`` / ``uninstall``.

Drops the binary at ``~/.local/bin/claude-qte``, registers the PreToolUse
hook in ``~/.claude/settings.json``, and (for upgrades) cleans up the
always-on LaunchAgent that 0.1.x installed.
"""

import contextlib
import os
import shutil
import subprocess
import sys

from claude_qte import settings as settings_mod
from claude_qte._platform import IS_MACOS
from claude_qte._runtime import DISABLED_FLAG
from claude_qte.settings import SETTINGS_PATH

INSTALL_BIN_DIR = os.path.expanduser("~/.local/bin")
INSTALL_BIN_NAME = "claude-qte"

# 0.1.x leftover — installed an always-on background daemon. We boot it out
# during install/uninstall so upgrades don't leave a zombie running.
LEGACY_PLIST_LABEL = "com.claudeqte.gate"
LEGACY_PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LEGACY_PLIST_LABEL}.plist")

COMMANDS_DIR = os.path.expanduser("~/.claude/commands")
_QTE_OFF_CMD = os.path.join(COMMANDS_DIR, "qte-off.md")
_QTE_ON_CMD = os.path.join(COMMANDS_DIR, "qte-on.md")
_QTE_OFF_CONTENT = """\
Run this exact shell command and report the output: `claude-qte disable`
"""
_QTE_ON_CONTENT = """\
Run this exact shell command and report the output: `claude-qte enable`
"""

CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
CLAUDE_MD_BEGIN = "<!-- claude-qte begin -->"
CLAUDE_MD_END = "<!-- claude-qte end -->"
_CLAUDE_MD_BLOCK = """\
<!-- claude-qte begin -->
## claude-qte (approval gate)

claude-qte intercepts tool-use permission prompts. When you are denied,
the reason is typed by the user in a popup — read it carefully and adjust
your approach accordingly. Do not retry the same action without addressing
the stated reason.

The PreToolUse hook handles routing automatically; you do not need to call
the gate directly.
<!-- claude-qte end -->"""


def patch_claude_md() -> None:
    """Append (or replace) the claude-qte block in ~/.claude/CLAUDE.md."""
    try:
        if os.path.exists(CLAUDE_MD_PATH):
            with open(CLAUDE_MD_PATH, encoding="utf-8") as fh:
                existing = fh.read()
        else:
            existing = ""
    except OSError:
        existing = ""

    if CLAUDE_MD_BEGIN in existing:
        start = existing.index(CLAUDE_MD_BEGIN)
        end = existing.find(CLAUDE_MD_END, start)
        if end != -1:
            end += len(CLAUDE_MD_END)
            new_content = existing[:start] + _CLAUDE_MD_BLOCK + existing[end:]
        else:
            new_content = existing[:start] + _CLAUDE_MD_BLOCK
    else:
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        new_content = existing + sep + _CLAUDE_MD_BLOCK + "\n"

    os.makedirs(os.path.dirname(CLAUDE_MD_PATH), exist_ok=True)
    with open(CLAUDE_MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_content)


def unpatch_claude_md() -> None:
    """Remove the claude-qte block from ~/.claude/CLAUDE.md if present."""
    if not os.path.exists(CLAUDE_MD_PATH):
        return
    try:
        with open(CLAUDE_MD_PATH, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return
    if CLAUDE_MD_BEGIN not in content:
        return
    start = content.index(CLAUDE_MD_BEGIN)
    end = content.find(CLAUDE_MD_END, start)
    if end == -1:
        new_content = content[:start].rstrip() + "\n"
    else:
        end += len(CLAUDE_MD_END)
        new_content = (content[:start] + content[end:]).strip()
        if new_content:
            new_content += "\n"
    with open(CLAUDE_MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_content)


def install_slash_commands() -> None:
    os.makedirs(COMMANDS_DIR, exist_ok=True)
    with open(_QTE_OFF_CMD, "w", encoding="utf-8") as fh:
        fh.write(_QTE_OFF_CONTENT)
    with open(_QTE_ON_CMD, "w", encoding="utf-8") as fh:
        fh.write(_QTE_ON_CONTENT)


def uninstall_slash_commands() -> None:
    for path in (_QTE_OFF_CMD, _QTE_ON_CMD):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


def _latest_github_tag() -> str:
    """Return the latest release tag name (without leading 'v') from GitHub, or ''."""
    import json
    import urllib.error
    import urllib.request

    url = "https://api.github.com/repos/adiletbaimyrza/claude-qte/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("tag_name", "").lstrip("v")
    except (urllib.error.URLError, OSError):
        return ""


def _editable_repo_path() -> str:
    """Return the on-disk repo path if this is an editable install, else ''."""
    import json

    try:
        import importlib.metadata

        pkg = importlib.metadata.distribution("claude-qte")
        direct_url = pkg.read_text("direct_url.json")
        if not direct_url:
            return ""
        data = json.loads(direct_url)
        if data.get("dir_info", {}).get("editable"):
            url = data.get("url", "")
            if url.startswith("file://"):
                return url[len("file://") :]
    except Exception:
        pass
    return ""


def run_update() -> None:
    """Check GitHub for a newer release and update accordingly."""
    from claude_qte import __version__

    print("  Checking for updates…")
    latest = _latest_github_tag()
    if not latest:
        print("  Could not reach GitHub or determine latest release.")
        sys.exit(1)

    current = __version__
    print(f"  Installed : {current}")
    print(f"  Latest    : {latest}")

    if latest == current:
        print("  Already up to date.")
        return

    repo_path = _editable_repo_path()
    if repo_path:
        # Editable install — just pull; the running code updates in place.
        print(f"  Pulling latest changes in {repo_path}…")
        result = subprocess.run(["git", "-C", repo_path, "pull"], check=False)
        if result.returncode != 0:
            print("  git pull failed.")
            sys.exit(1)
    else:
        # Regular pip install — reinstall from the tagged commit.
        install_url = f"git+https://github.com/adiletbaimyrza/claude-qte.git@v{latest}"
        print("  Running pip install --upgrade …")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                install_url,
                "--break-system-packages",
            ],
            check=False,
        )
        if result.returncode != 0:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", install_url],
                check=False,
            )
        if result.returncode != 0:
            print(f"  Update failed. Try manually:\n\n      pip install --upgrade '{install_url}'")
            sys.exit(1)

    print(f"\n  claude-qte updated to {latest}.\n")


def run_disable() -> None:
    os.makedirs(os.path.dirname(DISABLED_FLAG), exist_ok=True)
    with open(DISABLED_FLAG, "w"):
        pass
    print("  claude-qte disabled. Use /qte-on to re-enable.")


def run_enable() -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(DISABLED_FLAG)
    print("  claude-qte enabled.")


def run_install() -> None:
    bin_path = _install_binary()
    legacy_removed = remove_legacy_launch_agent()
    settings_mod.patch_for_hook(bin_path)
    patch_claude_md()
    install_slash_commands()

    legacy_note = ""
    if legacy_removed:
        legacy_note = "\n  Migrated from 0.1.x: the old always-on LaunchAgent has been removed.\n"

    print(f"""
  claude-qte installed.

  • Binary:  {bin_path}
  • Hook in: {SETTINGS_PATH}
{legacy_note}
  The gate auto-starts on first tool use — no alias required.

  For faster startup (no first-use delay), optionally add to your shell
  profile (e.g. ~/.bashrc or ~/.zshrc):

      alias claude='{bin_path} run claude'

  Open a new terminal and run `claude` to start.
""")
    if INSTALL_BIN_DIR not in os.environ.get("PATH", "").split(":"):
        print(f"  Note: add {INSTALL_BIN_DIR} to your PATH to run `claude-qte` directly.\n")


def run_uninstall() -> None:
    if remove_legacy_launch_agent():
        pass  # message already printed

    if settings_mod.unpatch_hook():
        print(f"  Removed claude-qte hook from {SETTINGS_PATH}")

    unpatch_claude_md()
    uninstall_slash_commands()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(DISABLED_FLAG)

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
        if IS_MACOS:
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
    if not IS_MACOS:
        return False
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
