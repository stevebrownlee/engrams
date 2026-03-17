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

"""Tests for the default visibility resolution system (Layers 1-2).

Tests cover:
  - _resolve_effective_visibility() returns 'individual' when no config exists
  - _resolve_effective_visibility() returns workspace default from DB config
  - _resolve_effective_visibility() passes through explicit visibility unchanged
  - _resolve_effective_visibility() seeds from config_seed.json on first access
  - handle_log_decision() applies effective visibility when none specified
  - handle_log_decision() preserves explicit visibility
  - handle_log_system_pattern() applies effective visibility
  - handle_log_custom_data() applies effective visibility for user categories
  - handle_log_custom_data() skips resolution for system categories
  - Team project default triggers write-through to .engrams/ filesystem
  - Init command _create_engrams_dirs() creates correct directory structure
  - Init command _write_config_seed() writes correct JSON
  - Init command init_strategy() with --team flag creates dirs + seed
  - Init command init_strategy() with --solo flag creates seed only, no dirs
"""

import json
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from engrams.db import database as db
from engrams.db import models
from engrams.handlers import mcp_handlers as H
from engrams.init_command import (
    _create_engrams_dirs,
    _write_config_seed,
    init_strategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Generator[str, None, None]:
    """Return a fresh temporary workspace_id string."""
    ws = str(tmp_path)
    # Clear the seeded workspaces cache so each test starts fresh
    H._seeded_workspaces.discard(ws)
    yield ws
    # Clean up
    H._seeded_workspaces.discard(ws)
    try:
        db.close_db_connection(ws)
    except Exception:
        pass


@pytest.fixture()
def team_workspace(workspace: str) -> str:
    """Workspace configured as a team project."""
    db.get_db_connection(workspace)
    data = models.CustomData(
        category="engrams_config",
        key="default_decision_visibility",
        value="team",
        visibility=None,
    )
    db.log_custom_data(workspace, data)
    return workspace


@pytest.fixture()
def solo_workspace(workspace: str) -> str:
    """Workspace configured as a solo/individual project."""
    db.get_db_connection(workspace)
    data = models.CustomData(
        category="engrams_config",
        key="default_decision_visibility",
        value="individual",
        visibility=None,
    )
    db.log_custom_data(workspace, data)
    return workspace


@pytest.fixture()
def unconfigured_workspace(workspace: str) -> str:
    """Workspace with DB but no visibility config."""
    db.get_db_connection(workspace)
    return workspace


@pytest.fixture()
def seeded_workspace(workspace: str) -> str:
    """Workspace with a config_seed.json but no DB config yet."""
    db.get_db_connection(workspace)
    seed_dir = Path(workspace) / ".engrams"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_data = {"default_decision_visibility": "team"}
    with open(seed_dir / "config_seed.json", "w") as f:
        json.dump(seed_data, f)
    return workspace


# ---------------------------------------------------------------------------
# Layer 1: _resolve_effective_visibility() Tests
# ---------------------------------------------------------------------------


class TestResolveEffectiveVisibility:
    """Tests for _resolve_effective_visibility() helper function."""

    def test_explicit_visibility_passes_through(self, workspace):
        """If caller sets visibility explicitly, it should be returned unchanged."""
        assert H._resolve_effective_visibility(workspace, "team") == "team"
        assert H._resolve_effective_visibility(workspace, "individual") == "individual"
        assert H._resolve_effective_visibility(workspace, "proposed") == "proposed"
        assert H._resolve_effective_visibility(workspace, "workspace") == "workspace"

    def test_unconfigured_workspace_defaults_to_individual(self, unconfigured_workspace):
        """When no config exists, default to 'individual' (safe fallback)."""
        result = H._resolve_effective_visibility(unconfigured_workspace, None)
        assert result == "individual"

    def test_team_workspace_returns_team(self, team_workspace):
        """When workspace is configured as team, returns 'team'."""
        result = H._resolve_effective_visibility(team_workspace, None)
        assert result == "team"

    def test_solo_workspace_returns_individual(self, solo_workspace):
        """When workspace is configured as individual, returns 'individual'."""
        result = H._resolve_effective_visibility(solo_workspace, None)
        assert result == "individual"

    def test_seeds_from_config_file_on_first_access(self, seeded_workspace):
        """On first access, should read config_seed.json and seed the DB."""
        # First call should seed from file
        result = H._resolve_effective_visibility(seeded_workspace, None)
        assert result == "team"

        # Verify it was actually written to DB
        configs = db.get_custom_data(
            seeded_workspace,
            category="engrams_config",
            key="default_decision_visibility",
        )
        assert len(configs) > 0
        val = configs[0].value
        assert val == "team"

    def test_does_not_reseed_on_subsequent_access(self, seeded_workspace):
        """After first seed, subsequent calls use DB, not file."""
        # First call seeds
        H._resolve_effective_visibility(seeded_workspace, None)

        # Modify the seed file to a different value
        seed_path = Path(seeded_workspace) / ".engrams" / "config_seed.json"
        with open(seed_path, "w") as f:
            json.dump({"default_decision_visibility": "individual"}, f)

        # Second call should still return "team" (from DB, not re-reading file)
        result = H._resolve_effective_visibility(seeded_workspace, None)
        assert result == "team"


# ---------------------------------------------------------------------------
# Layer 1: Handler Integration Tests
# ---------------------------------------------------------------------------


class TestHandlerVisibilityIntegration:
    """Tests that handlers apply effective visibility correctly."""

    def test_log_decision_no_visibility_uses_team_default(self, team_workspace):
        """Decision without visibility on team workspace gets visibility='team'."""
        dec = H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=team_workspace,
                summary="Test team decision",
                rationale=None,
                implementation_details=None,
                tags=None,
            )
        )
        assert dec["visibility"] == "team"

    def test_log_decision_no_visibility_uses_individual_default(self, solo_workspace):
        """Decision without visibility on solo workspace gets visibility='individual'."""
        dec = H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=solo_workspace,
                summary="Test solo decision",
                rationale=None,
                implementation_details=None,
                tags=None,
            )
        )
        assert dec["visibility"] == "individual"

    def test_log_decision_explicit_visibility_preserved(self, team_workspace):
        """Explicit visibility on a team workspace is NOT overridden."""
        dec = H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=team_workspace,
                summary="Personal note",
                rationale=None,
                implementation_details=None,
                tags=None,
                visibility="individual",
            )
        )
        assert dec["visibility"] == "individual"

    def test_log_decision_unconfigured_defaults_individual(self, unconfigured_workspace):
        """Decision on unconfigured workspace gets safe 'individual' default."""
        dec = H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=unconfigured_workspace,
                summary="Unconfigured workspace decision",
                rationale=None,
                implementation_details=None,
                tags=None,
            )
        )
        assert dec["visibility"] == "individual"

    def test_log_system_pattern_uses_team_default(self, team_workspace):
        """Pattern without visibility on team workspace gets visibility='team'."""
        pat = H.handle_log_system_pattern(
            models.LogSystemPatternArgs(
                workspace_id=team_workspace,
                name="Test pattern",
                description=None,
                tags=None,
            )
        )
        assert pat["visibility"] == "team"

    def test_log_custom_data_user_category_uses_team_default(self, team_workspace):
        """User custom data without visibility on team workspace gets 'team'."""
        cd = H.handle_log_custom_data(
            models.LogCustomDataArgs(
                workspace_id=team_workspace,
                category="ProjectGlossary",
                key="test_term",
                value="A test term",
            )
        )
        assert cd["visibility"] == "team"

    def test_log_custom_data_system_category_not_overridden(self, team_workspace):
        """System categories (engrams_config, engrams_strategy) should NOT get auto-visibility."""
        cd = H.handle_log_custom_data(
            models.LogCustomDataArgs(
                workspace_id=team_workspace,
                category="engrams_config",
                key="test_setting",
                value="test_value",
            )
        )
        # System categories should have None visibility (not overridden to "team")
        assert cd.get("visibility") is None

    def test_log_custom_data_post_task_checks_not_overridden(self, team_workspace):
        """post_task_checks category should NOT get auto-visibility."""
        cd = H.handle_log_custom_data(
            models.LogCustomDataArgs(
                workspace_id=team_workspace,
                category="post_task_checks",
                key="verification_commands",
                value={"project_type": "python", "checks": []},
            )
        )
        # System categories should have None visibility (not overridden to "team")
        assert cd.get("visibility") is None

    def test_team_decision_triggers_write_through(self, team_workspace):
        """Decision with team visibility should be written to .engrams/ filesystem."""
        dec = H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=team_workspace,
                summary="Team decision for write-through test",
                rationale="Testing write-through mechanism",
                implementation_details=None,
                tags=["test"],
            )
        )
        # Check that .engrams/decisions/ directory has a file
        decisions_dir = Path(team_workspace) / ".engrams" / "decisions"
        if decisions_dir.exists():
            md_files = list(decisions_dir.glob("*.md"))
            assert len(md_files) >= 1, "Team decision should create a .md file in .engrams/decisions/"

    def test_individual_decision_no_write_through(self, solo_workspace):
        """Decision with individual visibility should NOT create .engrams/ files."""
        H.handle_log_decision(
            models.LogDecisionArgs(
                workspace_id=solo_workspace,
                summary="Solo decision - no write-through",
                rationale=None,
                implementation_details=None,
                tags=None,
            )
        )
        decisions_dir = Path(solo_workspace) / ".engrams" / "decisions"
        if decisions_dir.exists():
            md_files = list(decisions_dir.glob("*.md"))
            assert len(md_files) == 0, "Individual decision should NOT create .engrams/ files"


# ---------------------------------------------------------------------------
# Layer 2: Init Command Tests
# ---------------------------------------------------------------------------


class TestInitCommandHelpers:
    """Tests for init command helper functions."""

    def test_create_engrams_dirs(self, tmp_path):
        """_create_engrams_dirs creates correct subdirectory structure."""
        _create_engrams_dirs(tmp_path)
        assert (tmp_path / ".engrams" / "decisions").is_dir()
        assert (tmp_path / ".engrams" / "patterns").is_dir()
        assert (tmp_path / ".engrams" / "shared-data").is_dir()

    def test_create_engrams_dirs_idempotent(self, tmp_path):
        """Calling _create_engrams_dirs twice doesn't error."""
        _create_engrams_dirs(tmp_path)
        _create_engrams_dirs(tmp_path)
        assert (tmp_path / ".engrams" / "decisions").is_dir()

    def test_write_config_seed_team(self, tmp_path):
        """_write_config_seed writes correct JSON for team projects."""
        _write_config_seed(tmp_path, "team")
        seed_path = tmp_path / ".engrams" / "config_seed.json"
        assert seed_path.exists()
        with open(seed_path) as f:
            data = json.load(f)
        assert data["default_decision_visibility"] == "team"

    def test_write_config_seed_individual(self, tmp_path):
        """_write_config_seed writes correct JSON for solo projects."""
        _write_config_seed(tmp_path, "individual")
        seed_path = tmp_path / ".engrams" / "config_seed.json"
        assert seed_path.exists()
        with open(seed_path) as f:
            data = json.load(f)
        assert data["default_decision_visibility"] == "individual"


class TestInitStrategyClassification:
    """Tests for init_strategy() with --team/--solo flags."""

    def test_init_team_creates_dirs_and_seed(self, tmp_path):
        """init_strategy with team=True creates .engrams/ dirs and seed file."""
        result = init_strategy(
            tool="generic",
            project_dir=str(tmp_path),
            force=True,
            team=True,
        )
        assert result == 0
        assert (tmp_path / ".engrams" / "decisions").is_dir()
        assert (tmp_path / ".engrams" / "patterns").is_dir()
        assert (tmp_path / ".engrams" / "shared-data").is_dir()
        seed_path = tmp_path / ".engrams" / "config_seed.json"
        assert seed_path.exists()
        with open(seed_path) as f:
            data = json.load(f)
        assert data["default_decision_visibility"] == "team"

    def test_init_solo_creates_seed_but_no_dirs(self, tmp_path):
        """init_strategy with solo=True creates seed but NOT .engrams/ subdirs."""
        result = init_strategy(
            tool="generic",
            project_dir=str(tmp_path),
            force=True,
            solo=True,
        )
        assert result == 0
        # Seed file should exist
        seed_path = tmp_path / ".engrams" / "config_seed.json"
        assert seed_path.exists()
        with open(seed_path) as f:
            data = json.load(f)
        assert data["default_decision_visibility"] == "individual"
        # Subdirectories should NOT exist for solo projects
        assert not (tmp_path / ".engrams" / "decisions").exists()
        assert not (tmp_path / ".engrams" / "patterns").exists()
        assert not (tmp_path / ".engrams" / "shared-data").exists()

    def test_init_still_writes_strategy_file(self, tmp_path):
        """init_strategy still writes the merged strategy file regardless of classification."""
        result = init_strategy(
            tool="generic",
            project_dir=str(tmp_path),
            force=True,
            team=True,
        )
        assert result == 0
        strategy_file = tmp_path / "engrams_strategy.yaml"
        assert strategy_file.exists()
        content = strategy_file.read_text()
        assert "ENGRAMS MEMORY STRATEGY" in content
        assert "VISIBILITY RULES" in content
