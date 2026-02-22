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

import logging
import os
import pathlib
from typing import Optional

# Placeholder for application settings and configuration logic

log = logging.getLogger(__name__)

# Global variable to store custom database path
_custom_db_path: Optional[str] = None
_base_path: Optional[str] = None
_db_filename: str = "context.db"


def set_custom_db_path(path: Optional[str]):
    """Set a custom database path."""
    global _custom_db_path
    _custom_db_path = path
    if path:
        log.info(f"Custom database path set to: {path}")


def set_base_path(path: Optional[str]):
    """Set a base database path."""
    global _base_path
    _base_path = path
    if path:
        log.info(f"Base path set to: {path}")


def set_db_filename(filename: str):
    """Set the database filename."""
    global _db_filename
    _db_filename = filename
    log.info(f"Database filename set to: {filename}")


def get_database_path(workspace_id: str) -> pathlib.Path:
    log.debug(f"get_database_path received workspace_id: {workspace_id}")
    """
    Determines the path to the SQLite database file for a given workspace.

    Args:
        workspace_id: An identifier for the workspace (e.g., the absolute path).

    Returns:
        The Path object pointing to the database file.

    Raises:
        ValueError: If the workspace_id is invalid or the path cannot be determined.
    """
    # Check if base database path is set
    if _base_path:
        base_path = pathlib.Path(_base_path).expanduser()
        sanitized_workspace_id = workspace_id.replace("/", "_").replace("\\", "_")
        db_dir = base_path / sanitized_workspace_id
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / _db_filename
        log.debug(f"Using base database path: {db_path}")
        return db_path

    # Check if custom database path is set
    if _custom_db_path:
        custom_path = pathlib.Path(_custom_db_path)
        if custom_path.is_absolute():
            # Absolute path - use as-is
            log.debug(f"Using custom absolute database path: {custom_path}")
            # Ensure parent directory exists
            custom_path.parent.mkdir(parents=True, exist_ok=True)
            return custom_path
        else:
            # Relative path - resolve relative to workspace
            posix_workspace_id = workspace_id.replace("\\", "/")
            workspace_path = pathlib.Path(posix_workspace_id)
            resolved_path = workspace_path / custom_path
            log.debug(f"Using custom relative database path: {resolved_path}")
            # Ensure parent directory exists
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            return resolved_path

    # Default behavior (unchanged)
    # Basic example: Assume workspace_id is the workspace root path
    # Store DB in a .context_portal directory within the workspace
    # Ensure workspace_id uses POSIX separators for consistency within Docker
    # This is a defensive measure against potential path mangling
    posix_workspace_id = workspace_id.replace("\\", "/")
    log.debug(f"Normalized workspace_id to POSIX: {posix_workspace_id}")

    if not posix_workspace_id or not os.path.isdir(posix_workspace_id):
        raise ValueError(f"Invalid workspace_id: {posix_workspace_id}")

    workspace_path = pathlib.Path(posix_workspace_id)
    log.debug(f"Constructed workspace_path: {workspace_path}")
    db_dir = workspace_path / "engrams"
    log.debug(f"Constructed db_dir: {db_dir}")
    log.debug(f"Attempting mkdir for: {db_dir}")
    db_dir.mkdir(exist_ok=True)  # Ensure the directory exists
    db_path = db_dir / _db_filename
    log.debug(f"Constructed db_path: {db_path}")
    return db_path
