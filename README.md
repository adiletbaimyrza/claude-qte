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
3. Installs a `LaunchAgent` so the gate runs in the background and starts at
   every login (no terminal window to keep open).
4. Adds a `PreToolUse` hook to `~/.claude/settings.json` so Claude Code
   itself enforces the gate — nothing for Claude to "remember to do."

Open a new Claude Code session and you're done.

## Uninstall

```sh
claude-qte uninstall
```

Removes the LaunchAgent, the hook entry from `~/.claude/settings.json`, and
the binary.

## How the "smart popup" works

Every time Claude Code is about to run a Bash / Edit / Write / NotebookEdit
tool, the hook decides:

- **You're at the terminal** (Terminal.app or iTerm2 is frontmost, its
  current tab is the one running Claude Code, and you've moved the keyboard
  or mouse in the last ~20 seconds) → hook returns `"ask"`, Claude Code's
  native inline prompt fires. No popup.
- **Otherwise** → hook spawns the QTE popup, blocks until you answer, and
  returns `"allow"` or `"deny"` to Claude Code.

Idle threshold and supported terminals are tunable inside `claude_qte.py`.

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

| Command                     | What it does                                    |
| --------------------------- | ----------------------------------------------- |
| `claude-qte`                | Run the gate (server mode). LaunchAgent uses it.|
| `claude-qte hook`           | PreToolUse hook entry point. Wired by `install`.|
| `claude-qte install`        | Install LaunchAgent + Claude Code hook.         |
| `claude-qte uninstall`      | Reverse `install`.                              |

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

## Build from source

```sh
pip install -r requirements-build.txt
pyinstaller --clean --noconfirm claude_qte.spec
# → dist/claude-qte
```

Or run as a script (macOS ships Python 3):

```sh
python3 claude_qte.py
```

## Why "qte"?

Quick-Time Event. In games, the action freezes and you must hit a button
*now* or fail. That's exactly what this does to Claude.
