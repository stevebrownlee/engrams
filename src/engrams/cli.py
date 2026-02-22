"""
Unified CLI entry point for Engrams.

Provides a subcommand-based interface:
    engrams serve [--mode stdio|http] [--host ...] [--port ...]
    engrams init --tool <name> [--list] [--force] [--project-dir ...]
    engrams dashboard [...]

For backward compatibility, `engrams-mcp` remains a direct entry point
to the MCP server (equivalent to `engrams serve`).
"""

import sys


# Known subcommands — used to distinguish subcommands from server flags
_SUBCOMMANDS = {"serve", "init", "dashboard"}


def main() -> None:
    """Unified CLI entry point for `engrams <subcommand> [flags]`."""
    # Determine the subcommand (first positional arg)
    if len(sys.argv) < 2:
        _print_help()
        return

    first_arg = sys.argv[1]

    # Top-level flags
    if first_arg in ("--help", "-h"):
        _print_help()
        return
    if first_arg == "--version":
        _print_version()
        return

    # If first arg is not a known subcommand, fall back to 'serve' (backward compat)
    # e.g. `engrams --mode stdio` → `engrams serve --mode stdio`
    if first_arg not in _SUBCOMMANDS:
        from .main import main_logic  # pylint: disable=import-outside-toplevel

        main_logic()
        return

    command = first_arg
    remaining_args = sys.argv[2:]

    if command == "serve":
        from .main import main_logic  # pylint: disable=import-outside-toplevel

        main_logic(sys_args=remaining_args)

    elif command == "init":
        from .init_command import (  # pylint: disable=import-outside-toplevel
            run_init_cli,
        )

        run_init_cli(sys_args=remaining_args)

    elif command == "dashboard":
        from .dashboard.app import main as dashboard_main  # pylint: disable=import-outside-toplevel

        # Dashboard uses its own argparse; pass remaining args via sys.argv override
        sys.argv = [sys.argv[0] + " dashboard"] + remaining_args
        dashboard_main()


def _print_help(file=None) -> None:
    """Print top-level help for the unified CLI."""
    if file is None:
        file = sys.stdout
    print(
        """Engrams — Enhanced Memory & Knowledge Platform for AI Agents

Usage:
    engrams <command> [options]

Commands:
    serve       Start the Engrams MCP server (default if no command given)
    init        Initialize Engrams strategy for an AI coding tool
    dashboard   Start the Engrams knowledge dashboard

Examples:
    engrams serve --mode stdio
    engrams init --tool windsurf
    engrams init --list
    engrams dashboard

Use 'engrams <command> --help' for details on each command.""",
        file=file,
    )


def _print_version() -> None:
    """Print the Engrams version."""
    try:
        from importlib.metadata import version  # pylint: disable=import-outside-toplevel

        v = version("engrams-mcp")
    except Exception:  # pylint: disable=broad-exception-caught
        v = "unknown"
    print(f"engrams {v}")
