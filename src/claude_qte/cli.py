"""Argparse + dispatch — entry point for ``claude-qte`` and ``python -m claude_qte``."""

import argparse
import os

from claude_qte import __version__

PORT_DEFAULT = 9999


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-qte",
        description="claude-qte — Claude Code approval gate",
    )
    parser.add_argument("--version", action="version", version=f"claude-qte {__version__}")

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
    run_p = sub.add_parser(
        "run",
        help="Start a per-session gate, run command, kill the gate on exit",
    )
    run_p.add_argument("argv", nargs=argparse.REMAINDER, help="Command to run (e.g. claude)")

    args = parser.parse_args()

    if args.cmd == "hook":
        # Per-session wrapper sets CLAUDE_QTE_PORT. Honor it over the default.
        from claude_qte.hook import run_hook

        env_port = os.environ.get("CLAUDE_QTE_PORT")
        port = int(env_port) if env_port and env_port.isdigit() else args.port
        run_hook(port)
    elif args.cmd == "install":
        from claude_qte.installer import run_install

        run_install()
    elif args.cmd == "uninstall":
        from claude_qte.installer import run_uninstall

        run_uninstall()
    elif args.cmd == "run":
        from claude_qte.wrapper import run_command

        run_command(args.argv)
    elif args.tui:
        from claude_qte.tui import run_tui

        run_tui(args.tui)
    else:
        from claude_qte.server import run_server

        run_server(args.port, parent_pid=args.parent_pid, quiet=args.quiet)


if __name__ == "__main__":
    main()
