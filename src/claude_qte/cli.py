"""Argparse + dispatch — entry point for ``claude-qte`` and ``python -m claude_qte``."""

import argparse

from claude_qte import __version__

PORT_DEFAULT = 9999


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-qte",
        description="claude-qte — Claude Code approval gate",
    )
    parser.add_argument("-v", "--version", action="version", version=f"claude-qte {__version__}")

    sub = parser.add_subparsers(dest="cmd")

    # Default (no subcommand) → server mode.
    parser.add_argument(
        "--port", type=int, default=PORT_DEFAULT, help="HTTP port to listen on (server mode)"
    )
    parser.add_argument("--tui", metavar="RID", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)

    sub.add_parser("hook", help="Run as a Claude Code PreToolUse hook")
    sub.add_parser("install", help="Install Claude Code hook")
    sub.add_parser("uninstall", help="Undo install")
    sub.add_parser("update", help="Update to the latest release")
    sub.add_parser("disable", help="Disable the gate (fall back to native prompts)")
    sub.add_parser("enable", help="Re-enable the gate")
    sound_p = sub.add_parser("sound", help="Manage notification sound")
    sound_sub = sound_p.add_subparsers(dest="sound_cmd")
    sound_sub.add_parser("list", help="List available sounds")
    sound_set_p = sound_sub.add_parser("set", help="Set active sound")
    sound_set_p.add_argument("name", help="Sound name (see 'sound list')")
    sound_sub.add_parser("off", help="Disable notification sound")
    sound_sub.add_parser("on", help="Re-enable notification sound")
    run_p = sub.add_parser(
        "run",
        help="Start a per-session gate, run command, kill the gate on exit",
    )
    run_p.add_argument("argv", nargs=argparse.REMAINDER, help="Command to run (e.g. claude)")

    denials_p = sub.add_parser("denials", help="Show the denial log (~/.claude/denials.log)")
    denials_p.add_argument(
        "-n",
        "--last",
        type=int,
        default=0,
        metavar="N",
        help="Show only the last N entries (default: all)",
    )
    denials_p.add_argument(
        "--clear",
        action="store_true",
        help="Clear the denial log",
    )

    args = parser.parse_args()

    if args.cmd == "hook":
        from claude_qte.hook import run_hook

        run_hook()
    elif args.cmd == "install":
        from claude_qte.installer import run_install

        run_install()
    elif args.cmd == "uninstall":
        from claude_qte.installer import run_uninstall

        run_uninstall()
    elif args.cmd == "update":
        from claude_qte.installer import run_update

        run_update()
    elif args.cmd == "sound":
        from claude_qte._sound import (
            DEFAULT_SOUND,
            SOUNDS,
            get_sound,
            is_muted,
            mute_sound,
            play_notification,
            set_sound,
            unmute_sound,
        )

        if args.sound_cmd == "list":
            current = get_sound()
            muted = is_muted()
            if muted:
                print("  Sound is currently off.\n")
            for name, label in SOUNDS.items():
                marker = " (active)" if name == current and not muted else ""
                default = " [default]" if name == DEFAULT_SOUND else ""
                print(f"  {name:<14} {label}{default}{marker}")
        elif args.sound_cmd == "set":
            if set_sound(args.name):
                print(f"  Sound set to '{args.name}'. Playing a preview…")
                play_notification()
                import time

                time.sleep(3)
            else:
                import sys

                print(f"  Unknown sound '{args.name}'. Run 'claude-qte sound list' to see options.")
                sys.exit(1)
        elif args.sound_cmd == "off":
            mute_sound()
            print("  Notification sound disabled. Use 'claude-qte sound on' to re-enable.")
        elif args.sound_cmd == "on":
            unmute_sound()
            print(f"  Notification sound enabled ('{get_sound()}').")
        else:
            sound_p.print_help()
    elif args.cmd == "disable":
        from claude_qte.installer import run_disable

        run_disable()
    elif args.cmd == "enable":
        from claude_qte.installer import run_enable

        run_enable()
    elif args.cmd == "run":
        from claude_qte.wrapper import run_command

        run_command(args.argv)
    elif args.cmd == "denials":
        from claude_qte.denial_log import DENIAL_LOG_PATH, print_denials

        if args.clear:
            import contextlib

            with contextlib.suppress(FileNotFoundError):
                import os

                os.unlink(DENIAL_LOG_PATH)
            print("  Denial log cleared.")
        else:
            print_denials(last=args.last)
    elif args.tui:
        from claude_qte.tui import run_tui

        run_tui(args.tui)
    else:
        from claude_qte.server import run_server

        run_server(args.port, parent_pid=args.parent_pid, quiet=args.quiet)


if __name__ == "__main__":
    main()
