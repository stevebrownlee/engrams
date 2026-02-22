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

"""Glob-based file matching utility for code bindings (Feature 2).

Provides functions to match file paths against glob patterns stored
in code_bindings, and optionally validate symbol patterns via simple
text search.
"""

import fnmatch
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


def match_file_against_pattern(file_path: str, pattern: str) -> bool:
    """
    Check if a file path matches a glob pattern.

    Supports:
    - Exact paths: src/auth/login.py
    - Glob patterns: src/auth/**/*.py
    - Simple wildcards: src/auth/*.py

    Args:
        file_path: Relative file path to check.
        pattern: Glob or exact path pattern.

    Returns:
        True if the file path matches the pattern.
    """
    # Normalize separators
    norm_file = file_path.replace("\\", "/")
    norm_pattern = pattern.replace("\\", "/")

    # Exact match
    if norm_file == norm_pattern:
        return True

    # fnmatch doesn't handle ** properly, so we handle it manually
    if "**" in norm_pattern:
        # Convert ** glob to regex
        regex = _glob_to_regex(norm_pattern)
        return bool(re.match(regex, norm_file))
    else:
        return fnmatch.fnmatch(norm_file, norm_pattern)


def match_files_in_workspace(workspace_path: str, pattern: str) -> List[str]:
    """
    Expand a glob pattern against the actual workspace filesystem.

    Args:
        workspace_path: Absolute path to the workspace root.
        pattern: Glob pattern to expand.

    Returns:
        List of matched file paths (relative to workspace root).
    """
    workspace = Path(workspace_path)
    if not workspace.is_dir():
        return []

    try:
        # Use pathlib's glob for ** support
        matched = list(workspace.glob(pattern))
        # Return relative paths
        return [str(m.relative_to(workspace)) for m in matched if m.is_file()]
    except (ValueError, OSError) as e:
        log.warning(f"Error matching pattern '{pattern}' in {workspace_path}: {e}")
        return []


def check_symbol_in_file(file_path: str, symbol_pattern: str) -> bool:
    """
    Simple text-based search for a symbol name in a file.

    This is intentionally simple — no AST parsing, just text search.
    Uses word boundaries and basic heuristics to avoid matching symbols
    within string literals. Good enough for 90% of cases.

    Args:
        file_path: Absolute path to the file.
        symbol_pattern: Symbol name or pattern to search for.

    Returns:
        True if the symbol is found in the file as a standalone symbol.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # Use word boundary regex with negative lookbehind/lookahead
        # to exclude matches that are immediately adjacent to quotes
        # This provides basic filtering of string literals
        pattern = r'(?<!["\'])\b' + re.escape(symbol_pattern) + r'\b(?!["\'])'
        return bool(re.search(pattern, content))
    except (IOError, OSError):
        return False


def verify_binding_pattern(
    workspace_path: str, file_pattern: str, symbol_pattern: Optional[str] = None
) -> Tuple[str, int, Optional[str]]:
    """
    Verify a binding's file and symbol patterns against the workspace.

    Args:
        workspace_path: Absolute path to the workspace root.
        file_pattern: Glob pattern for files.
        symbol_pattern: Optional symbol name to check.

    Returns:
        Tuple of (status, files_matched, notes).
        Status is one of: 'valid', 'file_missing', 'symbol_not_found', 'pattern_empty'.
    """
    matched_files = match_files_in_workspace(workspace_path, file_pattern)
    files_count = len(matched_files)

    if files_count == 0:
        return ("pattern_empty", 0, f"No files matched pattern '{file_pattern}'")

    if symbol_pattern:
        workspace = Path(workspace_path)
        symbol_found = False
        for rel_path in matched_files:
            abs_path = str(workspace / rel_path)
            if check_symbol_in_file(abs_path, symbol_pattern):
                symbol_found = True
                break

        if not symbol_found:
            return (
                "symbol_not_found",
                files_count,
                f"Pattern matched {files_count} file(s) but symbol '{symbol_pattern}' not found",
            )

    return ("valid", files_count, f"Pattern matched {files_count} file(s)")


def _glob_to_regex(pattern: str) -> str:
    """Convert a glob pattern with ** to a regex.

    ``**`` matches zero or more path segments (including none), while ``*``
    matches any characters within a single path component (no ``/``).
    """
    # Normalise separators
    pattern = pattern.replace("\\", "/")

    # Work segment-by-segment so that ** expansion is unambiguous.
    segments = pattern.split("/")
    regex_parts: list[str] = []

    for idx, seg in enumerate(segments):
        is_last = idx == len(segments) - 1
        if seg == "**":
            # Zero or more path segments, each followed by '/'
            regex_parts.append(r"(?:[^/]+/)*")
        else:
            # Escape regex specials, then restore glob wildcards
            escaped = re.escape(seg)
            escaped = escaped.replace(r"\*", "[^/]*")
            escaped = escaped.replace(r"\?", "[^/]")
            regex_parts.append(escaped if is_last else escaped + "/")

    return "^" + "".join(regex_parts) + "$"
