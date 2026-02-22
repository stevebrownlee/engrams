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
Backward compatibility helpers for ConPort → Engrams migration.

This module provides automatic migration and compatibility features to help
users transition from ConPort to Engrams without losing data or breaking
existing configurations.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def detect_and_migrate_old_conport(workspace_id: str) -> None:
    """
    Detect old ConPort directory structure and automatically migrate to Engrams.

    This function checks for the presence of old ConPort directories and files,
    and migrates them to the new Engrams structure if they exist.

    Args:
        workspace_id: The workspace path to check for migration
    """
    workspace = Path(workspace_id)
    old_db_path = workspace / "context_portal" / "context.db"
    new_db_path = workspace / "engrams" / "context.db"

    # Handle migration: if old path exists, migrate it
    if old_db_path.exists():
        if not new_db_path.exists():
            # Standard case: old exists, new doesn't - move old to new
            logger.info(
                f"Detected ConPort directory at {old_db_path.parent}, migrating to Engrams..."
            )
            try:
                # Create new engrams directory if it doesn't exist
                new_db_path.parent.mkdir(parents=True, exist_ok=True)

                # Move the entire context_portal directory to engrams
                shutil.move(str(old_db_path.parent), str(new_db_path.parent))
                logger.info("ConPort database migration complete")
            except Exception as e:
                logger.error(f"Failed to migrate ConPort directory: {e}")
                raise
        else:
            # Edge case: both exist - check which has more recent/valid data
            # If old database has data and new is empty/stale, use old
            try:
                import sqlite3
                old_conn = sqlite3.connect(str(old_db_path))
                new_conn = sqlite3.connect(str(new_db_path))

                old_cursor = old_conn.cursor()
                new_cursor = new_conn.cursor()

                old_cursor.execute("SELECT COUNT(*) FROM decisions")
                old_count = old_cursor.fetchone()[0]

                new_cursor.execute("SELECT COUNT(*) FROM decisions")
                new_count = new_cursor.fetchone()[0]

                old_conn.close()
                new_conn.close()

                # If old has more data, it's likely the active database
                if old_count > new_count:
                    logger.warning(
                        f"Both context_portal and engrams databases exist. "
                        f"Old database has {old_count} decisions, new has {new_count}. "
                        f"Removing stale new database and using old one."
                    )
                    try:
                        # Remove the stale new database
                        new_db_path.unlink()
                        # Move old to new location
                        new_db_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(old_db_path.parent), str(new_db_path.parent))
                        logger.info("Replaced stale database with active one")
                    except Exception as e:
                        logger.error(f"Failed to resolve database conflict: {e}")
                        raise
            except Exception as e:
                logger.debug(f"Could not compare databases: {e}")
                # If we can't compare, leave as-is
                pass

    # Migrate vector store if it exists
    old_vector_path = workspace / ".conport_vector_data"
    new_vector_path = workspace / ".engrams_vector_data"

    if old_vector_path.exists() and not new_vector_path.exists():
        logger.info(f"Detected ConPort vector data at {old_vector_path}, migrating...")
        try:
            shutil.move(str(old_vector_path), str(new_vector_path))
            logger.info("ConPort vector data migration complete")
        except Exception as e:
            logger.error(f"Failed to migrate ConPort vector data: {e}")
            raise


def get_workspace_with_fallback(
    explicit_workspace: Optional[str] = None, auto_detect: bool = True
) -> Optional[str]:
    """
    Get workspace ID with fallback to old ConPort environment variable.

    This function checks for workspace ID in the following order:
    1. Explicit workspace_id parameter
    2. ENGRAMS_WORKSPACE environment variable
    3. CONPORT_WORKSPACE environment variable (legacy)
    4. Auto-detection if enabled

    Args:
        explicit_workspace: Explicitly provided workspace ID
        auto_detect: Whether to enable auto-detection

    Returns:
        The workspace ID, or None if not found
    """
    # Check explicit workspace first
    if explicit_workspace:
        return explicit_workspace

    # Check new environment variable
    workspace = os.getenv("ENGRAMS_WORKSPACE")
    if workspace:
        return workspace

    # Check legacy environment variable
    workspace = os.getenv("CONPORT_WORKSPACE")
    if workspace:
        logger.warning(
            "Using legacy CONPORT_WORKSPACE environment variable. "
            "Please update to ENGRAMS_WORKSPACE for future compatibility."
        )
        return workspace

    # Auto-detection would happen in workspace_detector.py
    return None


def create_compatibility_symlink(workspace_id: str) -> None:
    """
    Create a symlink from old context_portal path to new engrams path for compatibility.

    This is optional and only recommended for development/testing environments.

    Args:
        workspace_id: The workspace path
    """
    workspace = Path(workspace_id)
    old_path = workspace / "context_portal"
    new_path = workspace / "engrams"

    # Only create symlink if new path exists and old doesn't
    if new_path.exists() and not old_path.exists():
        try:
            old_path.symlink_to(new_path)
            logger.info(f"Created compatibility symlink: {old_path} -> {new_path}")
        except Exception as e:
            logger.debug(f"Could not create compatibility symlink: {e}")
