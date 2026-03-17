"""
Tests for Option C — Belt & Suspenders database creation rigor.

Covers:
  - DatabaseNotInitializedError exception
  - create_database() extracted function
  - Auto-created workspace tracking (was_auto_created / clear_auto_created_flag)
  - get_db_connection() auto-creation flow
  - _augment_with_auto_create_notice() handler helper
  - _create_and_seed_database() in init_command
  - get_database_path() improved error messages
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
import os

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from engrams.core.exceptions import (
    DatabaseError,
    DatabaseNotInitializedError,
)
from engrams.db import database as db
from engrams.db import models
from engrams.handlers import mcp_handlers
from engrams.core import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def workspace(tmp_path: Path) -> str:
    """Return the path of a fresh temporary workspace."""
    ws = str(tmp_path)
    (tmp_path / "engrams").mkdir(parents=True, exist_ok=True)
    yield ws
    # Cleanup
    try:
        db.close_db_connection(ws)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_db_state():
    """Ensure each test starts with clean module-level state."""
    db._auto_created_workspaces.clear()
    yield
    db._auto_created_workspaces.clear()


# ===========================================================================
# 1. DatabaseNotInitializedError
# ===========================================================================

class TestDatabaseNotInitializedError:
    """Tests for the DatabaseNotInitializedError exception."""

    def test_inherits_from_database_error(self):
        err = DatabaseNotInitializedError(
            workspace_id="/tmp/test",
            db_path="/tmp/test/engrams/context.db",
        )
        assert isinstance(err, DatabaseError)

    def test_stores_workspace_id_and_db_path(self):
        err = DatabaseNotInitializedError(
            workspace_id="/tmp/ws",
            db_path="/tmp/ws/engrams/context.db",
            reason="test reason",
        )
        assert err.workspace_id == "/tmp/ws"
        assert err.db_path == "/tmp/ws/engrams/context.db"

    def test_message_includes_db_path(self):
        err = DatabaseNotInitializedError(
            workspace_id="/tmp/ws",
            db_path="/tmp/ws/engrams/context.db",
        )
        msg = str(err)
        assert "/tmp/ws/engrams/context.db" in msg
        assert "engrams init" in msg

    def test_message_includes_reason_when_provided(self):
        err = DatabaseNotInitializedError(
            workspace_id="/tmp/ws",
            db_path="/tmp/ws/engrams/context.db",
            reason="directory not writable",
        )
        msg = str(err)
        assert "directory not writable" in msg

    def test_message_omits_reason_when_empty(self):
        err = DatabaseNotInitializedError(
            workspace_id="/tmp/ws",
            db_path="/tmp/ws/engrams/context.db",
        )
        msg = str(err)
        # Should not have empty parens
        assert "()" not in msg


# ===========================================================================
# 2. create_database()
# ===========================================================================

class TestCreateDatabase:
    """Tests for the extracted create_database() function."""

    def test_creates_database_file(self, workspace: str):
        db_path = db.create_database(workspace)
        assert db_path.exists()
        assert db_path.name == "context.db"

    def test_returns_path_object(self, workspace: str):
        db_path = db.create_database(workspace)
        assert isinstance(db_path, Path)

    def test_idempotent_on_existing_db(self, workspace: str):
        """Calling create_database twice should not error."""
        db_path1 = db.create_database(workspace)
        db_path2 = db.create_database(workspace)
        assert db_path1 == db_path2
        assert db_path1.exists()

    def test_creates_engrams_directory_if_missing(self, tmp_path: Path):
        """Even without the engrams/ subdir pre-created, create_database should work."""
        ws = str(tmp_path)
        # Don't create engrams/ dir — let create_database handle it
        db_path = db.create_database(ws)
        assert db_path.exists()

    def test_database_has_schema_tables(self, workspace: str):
        """The created database should have the schema tables from migrations."""
        db_path = db.create_database(workspace)
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in cursor.fetchall()}
            # Core tables that should always exist
            assert "decisions" in tables
            assert "progress_entries" in tables
            assert "system_patterns" in tables
            assert "custom_data" in tables
        finally:
            conn.close()


# ===========================================================================
# 3. Auto-created workspace tracking
# ===========================================================================

class TestAutoCreatedTracking:
    """Tests for was_auto_created / clear_auto_created_flag."""

    def test_was_auto_created_false_by_default(self):
        assert db.was_auto_created("/nonexistent/workspace") is False

    def test_was_auto_created_true_after_auto_create(self, workspace: str):
        """get_db_connection on a new workspace sets the auto-created flag."""
        conn = db.get_db_connection(workspace)
        assert db.was_auto_created(workspace) is True
        db.close_db_connection(workspace)

    def test_clear_auto_created_flag(self, workspace: str):
        db.get_db_connection(workspace)
        assert db.was_auto_created(workspace) is True
        db.clear_auto_created_flag(workspace)
        assert db.was_auto_created(workspace) is False

    def test_clear_is_idempotent(self):
        """Clearing a flag that was never set should not raise."""
        db.clear_auto_created_flag("/nonexistent/ws")
        assert db.was_auto_created("/nonexistent/ws") is False

    def test_not_auto_created_when_db_exists_already(self, workspace: str):
        """If the DB already exists, get_db_connection should NOT set the flag."""
        # First call creates the DB
        db.get_db_connection(workspace)
        db.close_db_connection(workspace)
        db.clear_auto_created_flag(workspace)

        # Second call — DB already exists
        db.get_db_connection(workspace)
        assert db.was_auto_created(workspace) is False
        db.close_db_connection(workspace)


# ===========================================================================
# 4. _augment_with_auto_create_notice()
# ===========================================================================

class TestAugmentWithAutoCreateNotice:
    """Tests for the MCP handler augmentation helper."""

    def test_no_augmentation_when_not_auto_created(self):
        response = {"content": {}, "version": 1}
        result = mcp_handlers._augment_with_auto_create_notice("/fake/ws", response)
        assert result == response
        assert "_engrams_auto_initialized" not in result

    def test_augments_dict_response(self, workspace: str):
        # Trigger auto-creation
        db.get_db_connection(workspace)
        response = {"content": {}, "version": 1}
        result = mcp_handlers._augment_with_auto_create_notice(workspace, response)
        assert result["_engrams_auto_initialized"] is True
        assert "_notice" in result
        assert "engrams init" in result["_notice"]
        # Original data preserved
        assert result["content"] == {}
        assert result["version"] == 1

    def test_augments_list_response_by_wrapping(self, workspace: str):
        db.get_db_connection(workspace)
        response = [{"id": 1}, {"id": 2}]
        result = mcp_handlers._augment_with_auto_create_notice(workspace, response)
        assert result["_engrams_auto_initialized"] is True
        assert result["results"] == [{"id": 1}, {"id": 2}]

    def test_flag_cleared_after_first_augmentation(self, workspace: str):
        db.get_db_connection(workspace)
        response = {"content": {}}
        # First call — augmented
        result1 = mcp_handlers._augment_with_auto_create_notice(workspace, response)
        assert "_engrams_auto_initialized" in result1

        # Second call — no augmentation (flag was cleared)
        result2 = mcp_handlers._augment_with_auto_create_notice(workspace, response)
        assert "_engrams_auto_initialized" not in result2

    def test_passthrough_for_non_dict_non_list(self, workspace: str):
        db.get_db_connection(workspace)
        result = mcp_handlers._augment_with_auto_create_notice(workspace, "plain string")
        assert result == "plain string"


# ===========================================================================
# 5. Handler integration: get_product_context includes notice
# ===========================================================================

class TestHandlerAutoCreateNotice:
    """Integration test: dict-returning handlers include notice on auto-create."""

    def test_get_product_context_includes_notice(self, workspace: str):
        """The very first get_product_context call on a new workspace should
        include the auto-create notice since get_db_connection creates the DB."""
        args = models.GetContextArgs(workspace_id=workspace)
        result = mcp_handlers.handle_get_product_context(args)
        assert result.get("_engrams_auto_initialized") is True
        assert "engrams init" in result.get("_notice", "")

    def test_get_active_context_includes_notice(self, workspace: str):
        args = models.GetContextArgs(workspace_id=workspace)
        result = mcp_handlers.handle_get_active_context(args)
        assert result.get("_engrams_auto_initialized") is True

    def test_get_recent_activity_summary_includes_notice(self, workspace: str):
        args = models.GetRecentActivitySummaryArgs(
            workspace_id=workspace,
            hours_ago=24,
        )
        result = mcp_handlers.handle_get_recent_activity_summary(args)
        assert result.get("_engrams_auto_initialized") is True

    def test_notice_only_appears_once(self, workspace: str):
        """After the first handler returns the notice, subsequent calls should not."""
        args = models.GetContextArgs(workspace_id=workspace)
        result1 = mcp_handlers.handle_get_product_context(args)
        assert result1.get("_engrams_auto_initialized") is True

        result2 = mcp_handlers.handle_get_product_context(args)
        assert "_engrams_auto_initialized" not in result2


# ===========================================================================
# 6. get_database_path() improved error messages
# ===========================================================================

class TestGetDatabasePathErrors:
    """Tests for improved error messages in get_database_path()."""

    def test_raises_on_empty_workspace_id(self):
        with pytest.raises(ValueError, match="workspace_id"):
            config.get_database_path("")

    def test_raises_on_none_workspace_id(self):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            config.get_database_path(None)  # type: ignore

    def test_raises_on_nonexistent_directory(self):
        with pytest.raises(ValueError, match="does not exist"):
            config.get_database_path("/nonexistent/totally/fake/path")


# ===========================================================================
# 7. _create_and_seed_database() in init_command
# ===========================================================================

class TestCreateAndSeedDatabase:
    """Tests for the init_command._create_and_seed_database function."""

    def test_creates_database_and_seeds_visibility(self, tmp_path: Path):
        from engrams.init_command import _create_and_seed_database

        db_path = _create_and_seed_database(tmp_path, "team")
        assert db_path is not None
        assert db_path.exists()

        # Verify the seed was written
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM custom_data WHERE category='engrams_config' "
                "AND key='default_decision_visibility'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert "team" in row[0]
        finally:
            conn.close()

    def test_seeds_individual_visibility(self, tmp_path: Path):
        from engrams.init_command import _create_and_seed_database

        db_path = _create_and_seed_database(tmp_path, "individual")
        assert db_path is not None

        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM custom_data WHERE category='engrams_config' "
                "AND key='default_decision_visibility'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert "individual" in row[0]
        finally:
            conn.close()

    def test_returns_none_on_failure(self, tmp_path: Path):
        """If create_database fails, should return None not raise."""
        from engrams.init_command import _create_and_seed_database

        # Patch the source module since the import is local inside the function
        with patch("engrams.db.database.create_database", side_effect=Exception("fail")):
            result = _create_and_seed_database(tmp_path, "team")
            assert result is None
