# claude-qte

> Quick-Time Event for Claude Code.

Stops missing permission prompts. When Claude Code asks for permission and
you're staring at the terminal, the native inline prompt handles it as
usual. When you've wandered off — IDE, browser, Slack — a fresh **Terminal
window pops up**, sized to the request, with the same look as Claude Code's
prompt. It stays on top of other windows and plays a notification sound.
For Write/Edit tools it shows a colored unified diff. Answer; window
vanishes; Claude proceeds.

**Supports macOS and Linux** (X11 desktops; Wayland degrades gracefully).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/adiletbaimyrza/claude-qte/main/install.sh | sh
```

That single command:

1. Downloads the right binary for your platform (macOS arm64/x86\_64, Linux x86\_64).
2. Drops it in `~/.local/bin/claude-qte`.
3. Adds a `PreToolUse` hook to `~/.claude/settings.json` so Claude Code
   itself enforces the gate — nothing for Claude to "remember to do."
4. Appends a note to `~/.claude/CLAUDE.md` so Claude understands denial
   messages from the gate.

That's it — the gate **auto-starts on first tool use**, so no alias is
required. Just run `claude` as usual.

**Optional alias** — for zero first-use delay, add to your shell profile
(e.g. `~/.bashrc` or `~/.zshrc`):

```sh
alias claude='~/.local/bin/claude-qte run claude'
```

With the alias the gate starts before Claude Code and is killed with it;
without it the gate is lazily spawned on the first tool call (~200–400 ms
one-time delay per session).

Each session gets its own gate on a fresh free port, so multiple parallel
`claude` sessions don't fight over `:9999`.

## Uninstall

```sh
claude-qte uninstall
```

Removes the hook entry from `~/.claude/settings.json` and the binary
(plus any leftover `LaunchAgent` from 0.1.x). Also remove the `alias` line
from your shell profile.

## How the "smart popup" works

Every time Claude Code is about to run a Bash / Edit / Write / NotebookEdit
tool, the hook decides:

- **You're at the terminal** (the frontmost terminal window is the one
  running Claude Code, and you've moved the keyboard or mouse in the last
  ~20 seconds) → hook returns `"ask"`, Claude Code's native inline prompt
  fires. No popup.
- **Otherwise** → hook spawns the QTE popup, blocks until you answer, and
  returns `"allow"` or `"deny"` to Claude Code.

Presence detection per platform:

| Check | macOS | Linux (X11) | Linux (Wayland) |
|---|---|---|---|
| Idle time | `ioreg` (IOHIDSystem) | `xprintidle` | assume not idle |
| Frontmost terminal | AppleScript (Terminal.app / iTerm2) | `xdotool` + `/proc` fd scan | assume away → popup always shows |

Idle threshold is tunable at the top of `src/claude_qte/hook.py`
(`USER_PRESENCE_IDLE_SECONDS`).

**Linux optional dependencies** (install via your package manager for best results):

```sh
# Debian/Ubuntu
sudo apt install xdotool xprintidle wmctrl
# Arch
sudo pacman -S xdotool xprintidle wmctrl
# Fedora
sudo dnf install xdotool xprintidle wmctrl
```

`xprintidle` — idle detection · `xdotool` — frontmost terminal detection + window raising · `wmctrl` — window centering and always-on-top (all optional; missing tools degrade gracefully).

## How it feels (the popup)

**Bash commands** show the command and description:

```
  ✻ Claude Code                                   permission required
  ────────────────────────────────────────────────────────────────────

  Tool use
  ╭──────────────────────────────────────────────────────────────────╮
  │ Bash — publish 3 commits to github.com/<you>/claude-qte          │
  │                                                                  │
  │ $ git push origin main                                           │
  ╰──────────────────────────────────────────────────────────────────╯

  Do you want to proceed?
  ❯ 1. Yes
    2. No, and tell Claude what to do differently

  ────────────────────────────────────────────────────────────────────
  PgUp/PgDn scroll   ↑↓ select   ⏎ confirm   1 allow   2 deny+reply
```

**Write and Edit tools** show a colored unified diff instead of just the file path — green for additions, red for deletions, cyan for hunk headers. For `Write`, the diff is computed against the existing file on disk (or shown as a full addition for new files).

The window is sized to the request: tiny for `git status`, taller for a long diff. Pick `2` (or Esc) and a typed reply box opens — that text is sent back to Claude as the deny reason.

The popup window stays on top of other windows on X11 (via `wmctrl` + `xdotool`) and re-raises itself every second until you respond, so clicking elsewhere won't bury it.

A notification sound plays when the popup appears. Default is a clean notification chime; customize with `claude-qte sound`.

## Keyboard

| Key          | Action                          |
| ------------ | ------------------------------- |
| PgUp / PgDn  | Scroll the content panel        |
| Home / End   | Jump to top / bottom of panel   |
| ↑ / ↓        | Move Yes/No selection           |
| Enter        | Confirm selected option         |
| 1            | Quick allow                     |
| 2 / Esc      | Deny and open the reply prompt  |

## Slash commands

Once installed, three Claude Code slash commands are available in every session:

| Command      | What it does                                         |
| ------------ | ---------------------------------------------------- |
| `/qte-off`   | Disable the gate — Claude uses native prompts        |
| `/qte-on`    | Re-enable the gate                                   |
| `/qte-sound` | List sounds and switch the notification sound        |

Disabling writes `~/.config/claude-qte/disabled`; the hook sees it and
falls through to `"ask"` on every tool call. Enabling deletes the file.

## Subcommands

| Command                          | What it does                                          |
| -------------------------------- | ----------------------------------------------------- |
| `claude-qte run <cmd>...`        | Start a per-session gate, run `<cmd>`, kill the gate. |
| `claude-qte`                     | Run the gate directly (server mode).                  |
| `claude-qte hook`                | PreToolUse hook entry point. Wired by `install`.      |
| `claude-qte install`             | Drop the binary and register the Claude Code hook.    |
| `claude-qte uninstall`           | Reverse `install`.                                    |
| `claude-qte update`              | Fetch and install the latest release from GitHub.     |
| `claude-qte disable`             | Disable the gate (same as `/qte-off`).                |
| `claude-qte enable`              | Re-enable the gate (same as `/qte-on`).               |
| `claude-qte sound list`          | Show available notification sounds.                   |
| `claude-qte sound set <name>`    | Switch to a different sound (plays a preview).        |
| `claude-qte sound off`           | Mute the notification sound.                          |
| `claude-qte sound on`            | Unmute the notification sound.                        |

## API (the gate's HTTP surface)

The hook calls these — you usually don't need to.

### `POST /ask`

```sh
curl -s -X POST http://localhost:9999/ask \
     -H "Content-Type: application/json" \
     -d '{"q": "Delete node_modules in /Users/me/project"}'
```

Response:

```json
{ "approved": true,  "answer": "approved" }
{ "approved": false, "answer": "denied"   }
{ "approved": false, "answer": "<your typed reply>" }
```

### `GET /ping`  →  `{"status": "ok", "port": 9999}`

## Layout

```
claude-qte/
├── pyproject.toml
├── claude_qte.spec        # PyInstaller spec for the single-file binary
├── install.sh             # one-line installer (downloads release binary)
├── src/claude_qte/
│   ├── cli.py             # argparse + dispatch
│   ├── server.py          # HTTP gate (/ask, /ping)
│   ├── popup.py           # spawn terminal window, manage tmp-file handoff
│   ├── tui.py             # curses TUI (renders inside the spawned window)
│   ├── hook.py            # Claude Code PreToolUse hook + presence detection
│   ├── wrapper.py         # `claude-qte run` per-session lifecycle
│   ├── installer.py       # install / uninstall / update
│   ├── settings.py        # ~/.claude/settings.json patcher
│   ├── _platform.py       # macOS + Linux OS integration (idle, tty, terminal spawn)
│   ├── _runtime.py        # shared low-level helpers
│   ├── _sound.py          # notification sound (play, get/set, mute)
│   └── sounds/            # bundled mp3 notification sounds
└── tests/                 # pytest — pure logic + a couple of socket tests
```

## Develop

```sh
# Editable install + dev deps (pytest, ruff):
pip install -e ".[dev]"

# Run from source:
python -m claude_qte
python -m claude_qte run claude

# Tests:
pytest

# Lint + format:
ruff check        # static analysis
ruff format       # apply formatter
ruff format --check   # CI-style: fail if anything would change
```

CI runs `ruff check`, `ruff format --check`, and `pytest` on both macOS
and Ubuntu before building release binaries; a tag push (`v*`) attaches
both binaries (`claude-qte-macos-arm64`, `claude-qte-linux-x86_64`) to a
new GitHub release.

## Build the release binary

```sh
pip install -r requirements-build.txt
pip install .
pyinstaller --clean --noconfirm claude_qte.spec
# → dist/claude-qte
```

## Why "qte"?

Quick-Time Event. In games, the action freezes and you must hit a button
*now* or fail. That's exactly what this does to Claude.
