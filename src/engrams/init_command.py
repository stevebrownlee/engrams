# Copyright 2025 Scott McLeod (contextportal@gmail.com)
# Copyright 2025 Steve Brownlee (steve@stevebrownlee.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Engrams init command — scaffolds the Engrams strategy file into a project
for a specific AI coding tool.

Usage:
    engrams init --tool roo
    engrams init --tool cline
    engrams init --tool windsurf
    engrams init --tool cursor
    engrams init --tool claude-code
    engrams init --tool claude-desktop
    engrams init --tool generic
    engrams init --list
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Optional

import yaml

# Tool registry: maps --tool flag values to delta filenames and output targets
TOOL_REGISTRY: Dict[str, Dict[str, str]] = {
    "roo": {
        "template": "roo_code_engrams_strategy",  # kept for backward-compat reference
        "delta": "_delta_roo.yaml",
        "output": ".roo/rules/engrams_strategy",
        "description": "Roo Code — installs into .roo/rules/",
    },
    "cline": {
        "template": "cline_engrams_strategy",
        "delta": "_delta_cline.yaml",
        "output": ".clinerules",
        "description": "Cline — installs as .clinerules",
    },
    "windsurf": {
        "template": "windsurf_engrams_strategy",
        "delta": "_delta_windsurf.yaml",
        "output": ".windsurfrules",
        "description": "Windsurf (Cascade) — installs as .windsurfrules",
    },
    "cursor": {
        "template": "cursor_engrams_strategy",
        "delta": "_delta_cursor.yaml",
        "output": ".cursorrules",
        "description": "Cursor — installs as .cursorrules",
    },
    "claude-code": {
        "template": "claude_code_engrams_strategy",
        "delta": "_delta_claude_code.yaml",
        "output": "CLAUDE.md",
        "description": "Claude Code CLI — installs as CLAUDE.md",
    },
    "claude-desktop": {
        "template": "claude_desktop_engrams_strategy",
        "delta": "_delta_claude_desktop.yaml",
        "output": "engrams_strategy_claude_desktop.yaml",
        "description": "Claude Desktop — saves strategy file for pasting into settings",
    },
    "generic": {
        "template": "generic_engrams_strategy",
        "delta": "_delta_generic.yaml",
        "output": "engrams_strategy.yaml",
        "description": "Generic / Other — installs as engrams_strategy.yaml",
    },
}


def get_templates_dir() -> Path:
    """Returns the path to the bundled templates directory."""
    return Path(__file__).parent / "templates"


def merge_template(tool: str) -> str:
    """
    Merges the core strategy template with per-tool delta values.

    Args:
        tool: The tool identifier (e.g., 'roo', 'cline', 'cursor').

    Returns:
        The merged template string with all placeholders replaced.

    Raises:
        FileNotFoundError: If core or delta template files are not found.
        ValueError: If required delta keys are missing.
    """
    templates_dir = get_templates_dir()

    # Read core template
    core_path = templates_dir / "_core_strategy.yaml"
    if not core_path.exists():
        raise FileNotFoundError(f"Core template not found: {core_path}")

    with open(core_path, "r") as f:
        core_content = f.read()

    # Read delta file
    delta_filename = TOOL_REGISTRY[tool]["delta"]
    delta_path = templates_dir / delta_filename
    if not delta_path.exists():
        raise FileNotFoundError(f"Delta template not found: {delta_path}")

    with open(delta_path, "r") as f:
        delta_data = yaml.safe_load(f)

    if not delta_data:
        raise ValueError(f"Delta file is empty or invalid: {delta_path}")

    # Extract required delta values
    required_keys = [
        "header",
        "workspace_id_source",
        "list_files_action",
        "list_files_tool_line",
        "list_files_params",
        "workspace_id_step1",
    ]

    for key in required_keys:
        if key not in delta_data:
            raise ValueError(
                f"Delta file missing required key '{key}': {delta_path}"
            )

    # Perform substitutions
    merged = core_content
    merged = merged.replace("{{HEADER}}", delta_data["header"])
    merged = merged.replace(
        "{{WORKSPACE_ID_SOURCE}}", delta_data["workspace_id_source"]
    )
    merged = merged.replace(
        "{{LIST_FILES_ACTION}}", delta_data["list_files_action"]
    )
    merged = merged.replace(
        "{{LIST_FILES_PARAMS}}", delta_data["list_files_params"]
    )
    merged = merged.replace(
        "{{WORKSPACE_ID_STEP1}}", delta_data["workspace_id_step1"]
    )

    # Handle list_files_tool_line: if empty, remove the entire line
    tool_line = delta_data["list_files_tool_line"]
    if tool_line:
        merged = merged.replace("{{LIST_FILES_TOOL_LINE}}", tool_line)
    else:
        # Remove the line containing {{LIST_FILES_TOOL_LINE}}
        lines = merged.split("\n")
        merged = "\n".join(
            line for line in lines if "{{LIST_FILES_TOOL_LINE}}" not in line
        )

    return merged


def list_tools() -> None:
    """Prints all available tool targets."""
    print("Available tools for 'engrams init --tool <name>':\n")
    for name, info in TOOL_REGISTRY.items():
        print(f"  {name:<16} {info['description']}")
        print(f"  {'':<16} → {info['output']}")
        print()


def init_strategy(
    tool: str,
    project_dir: Optional[str] = None,
    force: bool = False,
) -> int:
    """
    Merges the core strategy template with per-tool delta and installs
    the result into the project directory.

    Args:
        tool: The tool identifier (e.g., 'roo', 'cline', 'cursor').
        project_dir: The project directory to install into. Defaults to cwd.
        force: If True, overwrite existing files without prompting.

    Returns:
        0 on success, 1 on error.
    """
    if tool not in TOOL_REGISTRY:
        print(f"Error: Unknown tool '{tool}'.", file=sys.stderr)
        print("Run 'engrams init --list' to see available tools.", file=sys.stderr)
        return 1

    entry = TOOL_REGISTRY[tool]
    output_relpath = entry["output"]

    # Merge core + delta
    try:
        merged_content = merge_template(tool)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "This may indicate a broken installation. "
            "Try reinstalling engrams-mcp.",
            file=sys.stderr,
        )
        return 1

    target_dir = Path(project_dir) if project_dir else Path.cwd()
    output_path = target_dir / output_relpath

    # Check if output already exists
    if output_path.exists() and not force:
        print(f"File already exists: {output_path}")
        try:
            response = input("Overwrite? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if response not in ("y", "yes"):
            print("Aborted.")
            return 1

    # Create parent directories if needed (e.g., .roo/rules/)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write merged content to output file
    with open(output_path, "w") as f:
        f.write(merged_content)

    print(f"✓ Engrams strategy installed for {tool}")
    print(f"  → {output_path}")

    # Tool-specific post-install hints
    if tool == "claude-desktop":
        print()
        print(
            "  Note: Copy the contents of this file into Claude Desktop's"
        )
        print("  Settings → Custom Instructions field.")
    elif tool == "claude-code":
        print()
        print(
            "  Claude Code will automatically read CLAUDE.md from your project root."
        )
    elif tool == "roo":
        print()
        print(
            "  Roo Code will automatically load rules from .roo/rules/."
        )

    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the init subcommand."""
    parser = argparse.ArgumentParser(
        prog="engrams init",
        description="Initialize Engrams strategy for an AI coding tool in your project.",
    )
    parser.add_argument(
        "--tool",
        type=str,
        choices=list(TOOL_REGISTRY.keys()),
        help="The AI coding tool to configure Engrams for.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_tools",
        help="List all available tool targets.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files without prompting.",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Target project directory. Defaults to current working directory.",
    )
    return parser


def run_init_cli(sys_args=None) -> None:
    """
    Run the init CLI.

    Args:
        sys_args: Optional list of args (for subcommand dispatch).
                   If None, uses sys.argv[1:].
    """
    parser = _build_parser()
    args = parser.parse_args(args=sys_args)

    if args.list_tools:
        list_tools()
        sys.exit(0)

    if not args.tool:
        parser.print_help()
        print(
            "\nError: --tool is required (or use --list to see options).",
            file=sys.stderr,
        )
        sys.exit(1)

    exit_code = init_strategy(
        tool=args.tool,
        project_dir=args.project_dir,
        force=args.force,
    )
    sys.exit(exit_code)


def cli_entry_point() -> None:
    """Legacy entry point for backward-compat 'engrams-init' script."""
    run_init_cli()
