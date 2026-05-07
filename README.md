# claude-qte

> Quick-Time Event for Claude Code.

Stops missing permission prompts. When Claude Code asks for permission and
you're staring at the terminal, the native inline prompt handles it as
usual. When you've wandered off — IDE, browser, Slack — a fresh **Terminal
window pops up at your cursor**, sized to the request, with the same look
as Claude Code's prompt. Answer; window vanishes; Claude proceeds.

**macOS only for now.** Windows / Linux later.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/adiletbaimyrza/claude-qte/main/install.sh | sh
```

That single command:

1. Downloads the right binary for your Mac (Apple Silicon or Intel).
2. Drops it in `~/.local/bin/claude-qte`.
3. Adds a `PreToolUse` hook to `~/.claude/settings.json` so Claude Code
   itself enforces the gate — nothing for Claude to "remember to do."

Then add this to your shell profile (e.g. `~/.zshrc`):

```sh
alias claude='~/.local/bin/claude-qte run claude'
```

Open a new terminal and `claude` will start the gate alongside it. The
gate runs only while that Claude Code session is alive — when claude exits
(normal exit, ctrl-c, terminal closed, even SIGKILL), the gate is killed
with it.

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

- **You're at the terminal** (Terminal.app or iTerm2 is frontmost, its
  current tab is the one running Claude Code, and you've moved the keyboard
  or mouse in the last ~20 seconds) → hook returns `"ask"`, Claude Code's
  native inline prompt fires. No popup.
- **Otherwise** → hook spawns the QTE popup, blocks until you answer, and
  returns `"allow"` or `"deny"` to Claude Code.

Idle threshold and supported terminals are tunable inside
`src/claude_qte/hook.py`.

## How it feels (the popup)

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
  ↑↓ select   ⏎ confirm   1 allow   2 deny+reply   esc deny+reply
```

The window is sized to the request: tiny for `git status`, taller for a
long file write. Pick `2` (or Esc) and a typed reply box opens — that text
is sent back to Claude as the deny reason.

## Keyboard

| Key      | Action                          |
| -------- | ------------------------------- |
| ↑ / ↓    | Move selection                  |
| Enter    | Confirm selected option         |
| 1        | Quick allow                     |
| 2 / Esc  | Deny and open the reply prompt  |

## Subcommands

| Command                     | What it does                                          |
| --------------------------- | ----------------------------------------------------- |
| `claude-qte run <cmd>...`   | Start a per-session gate, run `<cmd>`, kill the gate. |
| `claude-qte`                | Run the gate directly (server mode).                  |
| `claude-qte hook`           | PreToolUse hook entry point. Wired by `install`.      |
| `claude-qte install`        | Drop the binary and register the Claude Code hook.    |
| `claude-qte uninstall`      | Reverse `install`.                                    |

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
│   ├── popup.py           # spawn Terminal window, manage handoff
│   ├── tui.py             # curses TUI (renders inside the spawned window)
│   ├── hook.py            # Claude Code PreToolUse hook + presence detection
│   ├── wrapper.py         # `claude-qte run` per-session lifecycle
│   ├── installer.py       # install / uninstall / legacy LaunchAgent cleanup
│   ├── settings.py        # ~/.claude/settings.json patcher
│   └── _runtime.py        # shared low-level helpers
└── tests/                 # pytest — pure logic + a couple of socket tests
```

## Develop

```sh
# Editable install + dev deps:
pip install -e ".[dev]"

# Run from source:
python -m claude_qte
python -m claude_qte run claude

# Tests:
pytest
```

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
