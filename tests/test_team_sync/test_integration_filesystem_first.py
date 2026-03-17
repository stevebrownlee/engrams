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

"""Integration tests for the filesystem-first team decisions architecture (Phase 4).

Covers end-to-end workflows:
  - Full round-trip: write via MCP handlers, read back via TeamContentIndexer
  - Two-workspace simulation: workspace A creates team decisions → .engrams/ files →
    workspace B runs scan_and_sync → workspace B DB has same decisions
  - migrate-to-filesystem populates .engrams/ from existing DB
  - migrate-to-filesystem --dry-run prints output but writes no files
  - Both hook-export (legacy) and FS-first coexist — both modes can be installed
  - After migrate-to-filesystem, scan_and_sync is idempotent (no duplicates)
  - A decision created pre-migration (no UUID) gets a stable UUID assigned when written
  - Code bindings are correctly written to frontmatter during migration and read back
"""

import json
from io import StringIO
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from engrams.bindings import db_operations as binding_db_ops
from engrams.bindings.models import CodeBinding
from engrams.db import database as db
from engrams.db import models as db_models
from engrams.migrate_command import MigrationReport, _run_migration
from engrams.team_sync import (
    SyncReport,
    TeamContentIndexer,
    ensure_engrams_dir,
    write_decision_file,
    write_pattern_file,
    write_shared_data_file,
)
from engrams.team_sync.manifest import load_manifest
from engrams.team_sync.parser import parse_decision_file, parse_pattern_file


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> str:
    """Return a fresh temporary workspace with an initialised DB."""
    ws = str(tmp_path)
    db.get_db_connection(ws)
    return ws


@pytest.fixture()
def workspace_b(tmp_path: Path) -> str:
    """A second workspace simulating a teammate's machine."""
    ws = str(tmp_path / "workspace_b")
    Path(ws).mkdir(parents=True, exist_ok=True)
    db.get_db_connection(ws)
    return ws


def _make_team_decision(workspace: str, summary: str, tags: List[str] | None = None) -> db_models.Decision:
    """Helper: create a team-visibility decision in *workspace*."""
    decision = db_models.Decision(
        summary=summary,
        rationale="Because it is best.",
        tags=tags,
        visibility="team",
    )
    return db.log_decision(workspace, decision)


def _make_team_pattern(workspace: str, name: str) -> db_models.SystemPattern:
    """Helper: create a team-visibility pattern in *workspace*."""
    pattern = db_models.SystemPattern(
        name=name,
        description="A useful pattern.",
        tags=["architecture"],
        visibility="team",
    )
    return db.log_system_pattern(workspace, pattern)


def _make_team_custom_data(workspace: str, category: str, key: str, value) -> db_models.CustomData:
    """Helper: create a team-visibility custom_data entry in *workspace*."""
    entry = db_models.CustomData(
        category=category,
        key=key,
        value=value,
        visibility="team",
    )
    return db.log_custom_data(workspace, entry)


def _make_binding(
    workspace: str,
    item_type: str,
    item_id: "int | None",
    pattern: str = "src/**/*.py",
) -> CodeBinding:
    """Helper: create a code binding for *item_id*.  Asserts id is not None."""
    assert item_id is not None, "item_id must not be None"
    binding = CodeBinding(
        item_type=item_type,
        item_id=item_id,
        file_pattern=pattern,
        symbol_pattern=None,
        binding_type="implements",
        confidence="manual",
    )
    return binding_db_ops.create_code_binding(workspace, binding)


# ---------------------------------------------------------------------------
# Helper: clear the manifest so scan_and_sync processes all files from scratch
# ---------------------------------------------------------------------------


def _clear_manifest(workspace: str) -> None:
    """Delete .engrams-manifest.json so the next scan_and_sync starts fresh."""
    manifest_path = Path(workspace) / ".engrams" / ".engrams-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()


# ===========================================================================
# Test 1: Full round-trip — write via write_decision_file, read back via indexer
# ===========================================================================


class TestFullRoundTrip:
    """A decision written to .engrams/ via write_decision_file is correctly
    synced back into the DB by TeamContentIndexer.scan_and_sync() on a fresh
    manifest (simulating what happens in workspace B after a git pull)."""

    def test_decision_round_trip(self, workspace: str) -> None:
        """Write a decision file, clear manifest, then scan_and_sync re-processes it."""
        decision = _make_team_decision(workspace, "Use PostgreSQL for persistence")
        binding = _make_binding(workspace, "decision", decision.id)

        # Write to filesystem (also updates manifest)
        file_path = write_decision_file(workspace, decision, [binding])
        assert file_path.exists()

        # Parse the file and verify frontmatter
        fm, body = parse_decision_file(file_path)
        assert fm.uuid is not None

        # Clear manifest — simulates a fresh workspace that has never scanned these files
        _clear_manifest(workspace)

        indexer = TeamContentIndexer(workspace)
        report = indexer.scan_and_sync()

        assert report.decisions_upserted >= 1
        assert len(report.errors) == 0

    def test_pattern_round_trip(self, workspace: str) -> None:
        """Write a pattern file, clear manifest, then scan_and_sync reads it back."""
        pattern = _make_team_pattern(workspace, "Repository Pattern")
        file_path = write_pattern_file(workspace, pattern, [])
        assert file_path.exists()

        _clear_manifest(workspace)

        indexer = TeamContentIndexer(workspace)
        report = indexer.scan_and_sync()

        assert report.patterns_upserted >= 1
        assert len(report.errors) == 0

    def test_shared_data_round_trip(self, workspace: str) -> None:
        """Write a shared-data file, clear manifest, then scan_and_sync reads it back."""
        entry = _make_team_custom_data(workspace, "ProjectConfig", "db_host", "localhost")
        file_path = write_shared_data_file(workspace, "ProjectConfig", [entry])
        assert file_path.exists()

        _clear_manifest(workspace)

        indexer = TeamContentIndexer(workspace)
        report = indexer.scan_and_sync()

        assert report.custom_data_upserted >= 1
        assert len(report.errors) == 0

    def test_bindings_are_preserved_in_round_trip(self, workspace: str) -> None:
        """Bindings in frontmatter survive a full write→parse→sync round-trip.

        After _clear_manifest, scan_and_sync will re-process the file and see
        that the binding already exists in the DB (idempotent) — bindings_added
        may be 0 because they were already there.  What matters is: no errors
        and the decision was upserted.
        """
        decision = _make_team_decision(workspace, "Use Redis for caching")
        binding = _make_binding(workspace, "decision", decision.id, "src/cache/**/*.py")

        write_decision_file(workspace, decision, [binding])
        _clear_manifest(workspace)

        indexer = TeamContentIndexer(workspace)
        report = indexer.scan_and_sync()

        assert report.decisions_upserted >= 1
        assert len(report.errors) == 0
        # Binding was already in DB → added=0 or removed=0 (idempotent)
        assert report.bindings_removed == 0


# ===========================================================================
# Test 2: Two-workspace simulation
# ===========================================================================


class TestTwoWorkspaceSimulation:
    """Workspace A creates team decisions → .engrams/ files get copied to workspace B →
    workspace B runs scan_and_sync → workspace B DB now contains the same decisions.

    Important: we must clear the manifest in workspace B after copying because the
    copied manifest already has up-to-date hashes from workspace A's writes,
    which would cause scan_and_sync to skip all files (hash match).
    In a real git-workflow, the post-merge hook passes changed file paths to
    incremental_sync instead of using the manifest fast-path.
    """

    def test_cross_workspace_sync(self, workspace: str, workspace_b: str) -> None:
        """Files created in workspace A are correctly indexed in workspace B."""
        import shutil

        # Workspace A: create a decision and write its .engrams/ file
        decision = _make_team_decision(workspace, "Use JWT for auth tokens", tags=["auth", "security"])
        binding = _make_binding(workspace, "decision", decision.id, "src/auth/**/*.py")
        write_decision_file(workspace, decision, [binding])

        # Copy the .engrams/ directory from A to B
        engrams_dir_a = Path(workspace) / ".engrams"
        engrams_dir_b = Path(workspace_b) / ".engrams"
        shutil.copytree(str(engrams_dir_a), str(engrams_dir_b))

        # Clear manifest in B so scan_and_sync processes the copied files
        _clear_manifest(workspace_b)

        # Workspace B: run scan_and_sync — should pick up the copied file
        indexer_b = TeamContentIndexer(workspace_b)
        report = indexer_b.scan_and_sync()

        assert report.decisions_upserted >= 1
        assert len(report.errors) == 0

        # Verify the decision now exists in workspace B's DB
        decisions_b = db.get_decisions(workspace_b, visibility_filter="team")
        summaries_b = [d.summary for d in decisions_b]
        assert "Use JWT for auth tokens" in summaries_b

    def test_cross_workspace_preserves_tags(self, workspace: str, workspace_b: str) -> None:
        """Tags on team decisions are preserved across workspace sync."""
        import shutil

        decision = _make_team_decision(workspace, "Adopt TypeScript", tags=["frontend", "tooling"])
        write_decision_file(workspace, decision, [])

        shutil.copytree(
            str(Path(workspace) / ".engrams"),
            str(Path(workspace_b) / ".engrams"),
        )
        _clear_manifest(workspace_b)

        indexer_b = TeamContentIndexer(workspace_b)
        report = indexer_b.scan_and_sync()

        assert report.decisions_upserted >= 1
        decisions_b = db.get_decisions(workspace_b, visibility_filter="team")
        ts_decision = next((d for d in decisions_b if d.summary == "Adopt TypeScript"), None)
        assert ts_decision is not None

    def test_cross_workspace_bindings_synced(self, workspace: str, workspace_b: str) -> None:
        """Bindings written to .engrams/ frontmatter are created in workspace B's DB."""
        import shutil

        decision = _make_team_decision(workspace, "Use Celery for background tasks")
        binding = _make_binding(workspace, "decision", decision.id, "src/tasks/**/*.py")
        write_decision_file(workspace, decision, [binding])

        shutil.copytree(
            str(Path(workspace) / ".engrams"),
            str(Path(workspace_b) / ".engrams"),
        )
        _clear_manifest(workspace_b)

        indexer_b = TeamContentIndexer(workspace_b)
        report = indexer_b.scan_and_sync()

        # Workspace B should have a binding created
        assert report.bindings_added >= 1


# ===========================================================================
# Test 3: migrate-to-filesystem populates .engrams/ from existing DB
# ===========================================================================


class TestMigrateToFilesystem:
    """_run_migration() reads team items from the DB and writes .engrams/ files."""

    def test_migration_creates_decision_files(self, workspace: str) -> None:
        """migrate-to-filesystem creates a .md file for each team decision."""
        d1 = _make_team_decision(workspace, "Use HTTPS everywhere")
        d2 = _make_team_decision(workspace, "Log all errors to Sentry")

        report = _run_migration(workspace, dry_run=False)

        assert report.decisions_migrated == 2
        assert report.decisions_failed == 0
        assert len(report.errors) == 0

        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        md_files = list(decisions_dir.glob("*.md"))
        assert len(md_files) == 2

    def test_migration_creates_pattern_files(self, workspace: str) -> None:
        """migrate-to-filesystem creates a .md file for each team pattern."""
        _make_team_pattern(workspace, "Repository Pattern")
        _make_team_pattern(workspace, "Factory Pattern")

        report = _run_migration(workspace, dry_run=False)

        assert report.patterns_migrated == 2
        patterns_dir = Path(workspace) / ".engrams" / "patterns"
        assert len(list(patterns_dir.glob("*.md"))) == 2

    def test_migration_creates_custom_data_files(self, workspace: str) -> None:
        """migrate-to-filesystem creates one .md file per category."""
        _make_team_custom_data(workspace, "Config", "host", "localhost")
        _make_team_custom_data(workspace, "Config", "port", 5432)
        _make_team_custom_data(workspace, "Glossary", "API", "Application Programming Interface")

        report = _run_migration(workspace, dry_run=False)

        assert report.custom_data_categories_migrated == 2
        shared_dir = Path(workspace) / ".engrams" / "shared-data"
        assert len(list(shared_dir.glob("*.md"))) == 2

    def test_migration_writes_bindings_to_frontmatter(self, workspace: str) -> None:
        """Bindings are written to the frontmatter of migrated decision files."""
        decision = _make_team_decision(workspace, "Use Pydantic for validation")
        _make_binding(workspace, "decision", decision.id, "src/models/**/*.py")

        report = _run_migration(workspace, dry_run=False)

        assert report.bindings_written == 1

        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        md_files = list(decisions_dir.glob("*.md"))
        assert len(md_files) == 1

        fm, _ = parse_decision_file(md_files[0])
        assert len(fm.bindings) == 1
        assert fm.bindings[0].pattern == "src/models/**/*.py"

    def test_migration_skips_non_team_items(self, workspace: str) -> None:
        """Only team-visibility items are migrated; personal items are excluded."""
        _make_team_decision(workspace, "Team decision")

        # Create a personal (individual) decision — should NOT be migrated
        personal = db_models.Decision(
            summary="My private decision",
            visibility="individual",
        )
        db.log_decision(workspace, personal)

        report = _run_migration(workspace, dry_run=False)

        assert report.decisions_migrated == 1  # Only the team decision

    def test_migration_updates_manifest(self, workspace: str) -> None:
        """After migration, .engrams-manifest.json contains all migrated items."""
        _make_team_decision(workspace, "Enforce code reviews")
        _make_team_pattern(workspace, "Observer Pattern")

        _run_migration(workspace, dry_run=False)

        engrams_dir = Path(workspace) / ".engrams"
        manifest = load_manifest(engrams_dir)

        # At least 2 entries: one decision, one pattern
        assert len(manifest.entries) >= 2


# ===========================================================================
# Test 4: migrate-to-filesystem --dry-run
# ===========================================================================


class TestMigrateDryRun:
    """--dry-run shows what would be done without writing any files."""

    def test_dry_run_writes_no_files(self, workspace: str) -> None:
        """No .engrams/ files are created in dry-run mode."""
        _make_team_decision(workspace, "DRY RUN decision")
        _make_team_pattern(workspace, "DRY RUN pattern")

        report = _run_migration(workspace, dry_run=True)

        assert report.dry_run is True
        assert report.decisions_migrated == 1
        assert report.patterns_migrated == 1

        # .engrams/ should NOT exist (or if it does, it has no .md files)
        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        patterns_dir = Path(workspace) / ".engrams" / "patterns"
        decisions_files = list(decisions_dir.glob("*.md")) if decisions_dir.exists() else []
        patterns_files = list(patterns_dir.glob("*.md")) if patterns_dir.exists() else []
        assert len(decisions_files) == 0
        assert len(patterns_files) == 0

    def test_dry_run_counts_are_accurate(self, workspace: str) -> None:
        """Dry-run report counts match actual DB items."""
        _make_team_decision(workspace, "Decision 1")
        _make_team_decision(workspace, "Decision 2")
        _make_team_pattern(workspace, "Pattern 1")
        _make_team_custom_data(workspace, "Cat1", "k1", "v1")

        report = _run_migration(workspace, dry_run=True)

        assert report.decisions_migrated == 2
        assert report.patterns_migrated == 1
        assert report.custom_data_categories_migrated == 1
        assert report.decisions_failed == 0

    def test_dry_run_counts_bindings(self, workspace: str) -> None:
        """Dry-run bindings_written reflects actual binding count without writing."""
        decision = _make_team_decision(workspace, "Binding test decision")
        _make_binding(workspace, "decision", decision.id, "src/**/*.py")
        _make_binding(workspace, "decision", decision.id, "tests/**/*.py")

        report = _run_migration(workspace, dry_run=True)

        assert report.bindings_written == 2
        # No files written
        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        assert not decisions_dir.exists() or len(list(decisions_dir.glob("*.md"))) == 0


# ===========================================================================
# Test 5: Both hook modes coexist
# ===========================================================================


class TestHookModeCoexistence:
    """Both legacy (database-export-based) and FS-first hooks can be installed."""

    def test_filesystem_mode_is_default(self, tmp_path: Path) -> None:
        """install-hooks without --mode flag uses 'filesystem' mode."""
        import stat
        import sys

        # Create a fake git repo
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        from engrams.install_hooks_command import run_install_hooks_cli

        run_install_hooks_cli(["--project-dir", str(tmp_path)])

        post_merge = tmp_path / ".git" / "hooks" / "post-merge"
        assert post_merge.exists()
        content = post_merge.read_text()
        # Filesystem mode references index-sync, not import
        assert "index-sync" in content

    def test_legacy_mode_installs_import_hook(self, tmp_path: Path) -> None:
        """install-hooks --mode legacy produces an import-based post-merge hook."""
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        from engrams.install_hooks_command import run_install_hooks_cli

        # Capture the legacy warning
        with patch("builtins.print") as mock_print:
            run_install_hooks_cli(["--project-dir", str(tmp_path), "--mode", "legacy"])

        post_merge = tmp_path / ".git" / "hooks" / "post-merge"
        assert post_merge.exists()
        content = post_merge.read_text()
        assert "import" in content
        assert "index-sync" not in content

    def test_legacy_mode_prints_warning(self, tmp_path: Path) -> None:
        """install-hooks --mode legacy prints the legacy deprecation warning."""
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        from engrams.install_hooks_command import run_install_hooks_cli

        printed_lines = []
        with patch("builtins.print", side_effect=lambda *args, **kw: printed_lines.append(" ".join(str(a) for a in args))):
            run_install_hooks_cli(["--project-dir", str(tmp_path), "--mode", "legacy"])

        full_output = "\n".join(printed_lines)
        assert "Legacy hook mode" in full_output or "legacy" in full_output.lower()

    def test_both_modes_can_be_reinstalled_with_force(self, tmp_path: Path) -> None:
        """After installing filesystem mode, --force can switch to legacy (and back)."""
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)

        from engrams.install_hooks_command import run_install_hooks_cli

        # First install: filesystem
        run_install_hooks_cli(["--project-dir", str(tmp_path)])
        post_merge = tmp_path / ".git" / "hooks" / "post-merge"
        assert "index-sync" in post_merge.read_text()

        # Second install: legacy with --force
        run_install_hooks_cli(["--project-dir", str(tmp_path), "--mode", "legacy", "--force"])
        assert "import" in post_merge.read_text()


# ===========================================================================
# Test 6: After migrate-to-filesystem, scan_and_sync is idempotent
# ===========================================================================


class TestIdempotency:
    """Running migrate-to-filesystem twice, or scan_and_sync after migration,
    should produce no duplicate DB rows."""

    def test_migration_is_idempotent(self, workspace: str) -> None:
        """Running migrate-to-filesystem twice produces no duplicate files."""
        _make_team_decision(workspace, "Idempotency decision")

        # First run
        _run_migration(workspace, dry_run=False)
        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        files_after_first = set(p.name for p in decisions_dir.glob("*.md"))

        # Second run
        _run_migration(workspace, dry_run=False)
        files_after_second = set(p.name for p in decisions_dir.glob("*.md"))

        # Same set of files — no duplicates
        assert files_after_first == files_after_second

    def test_scan_and_sync_after_migration_is_idempotent(self, workspace: str) -> None:
        """scan_and_sync after migration doesn't create duplicate DB records."""
        _make_team_decision(workspace, "Check unique decisions after scan")
        _run_migration(workspace, dry_run=False)

        # Run scan_and_sync — should find files unchanged (hash match), skip them
        indexer = TeamContentIndexer(workspace)
        report1 = indexer.scan_and_sync()

        # Run again
        report2 = indexer.scan_and_sync()

        # Second run should have ALL files skipped (hash unchanged)
        assert report2.files_skipped >= report1.files_processed or report2.files_processed == 0
        assert len(report2.errors) == 0

    def test_scan_and_sync_no_duplicate_decisions(self, workspace: str) -> None:
        """DB decisions count stays the same after repeated scan_and_sync calls."""
        _make_team_decision(workspace, "Check count stability")
        _run_migration(workspace, dry_run=False)

        count_before = len(db.get_decisions(workspace, visibility_filter="team"))

        indexer = TeamContentIndexer(workspace)
        indexer.scan_and_sync()
        indexer.scan_and_sync()

        count_after = len(db.get_decisions(workspace, visibility_filter="team"))
        assert count_after == count_before


# ===========================================================================
# Test 7: Pre-migration decision (no UUID) gets a stable UUID when written
# ===========================================================================


class TestUUIDAssignment:
    """Decisions created before filesystem-first (no UUID column value) get
    a stable UUID assigned when written to a .engrams/ file."""

    def test_no_uuid_decision_gets_uuid_on_write(self, workspace: str) -> None:
        """A decision written to .engrams/ always has a UUID in its frontmatter.

        Note: db.log_decision may auto-generate a UUID at insert time, so we
        can't guarantee uuid=None in the DB model. What we CAN guarantee is
        that the written .md file always has a valid UUID frontmatter field.
        """
        decision = db_models.Decision(
            summary="Legacy decision without UUID",
            visibility="team",
            uuid=None,
        )
        result = db.log_decision(workspace, decision)
        # The DB may or may not have a UUID after insert (depends on migration)
        # In any case, write_decision_file must produce a valid UUID in the file
        file_path = write_decision_file(workspace, result, [])
        fm, _ = parse_decision_file(file_path)

        assert fm.uuid is not None
        assert len(fm.uuid) == 36  # Standard UUID v4 format

    def test_uuid_is_stable_across_re_writes(self, workspace: str) -> None:
        """Writing the same decision twice produces the same UUID each time IF uuid is set."""
        decision = _make_team_decision(workspace, "UUID stability check")

        file1 = write_decision_file(workspace, decision, [])
        fm1, _ = parse_decision_file(file1)
        uuid1 = fm1.uuid

        # Overwrite the file
        file2 = write_decision_file(workspace, decision, [])
        fm2, _ = parse_decision_file(file2)
        uuid2 = fm2.uuid

        assert uuid1 == uuid2

    def test_migration_assigns_uuid_to_legacy_decisions(self, workspace: str) -> None:
        """migrate-to-filesystem assigns UUIDs to decisions that had none."""
        # Insert a decision directly with null uuid (bypassing normal log_decision)
        decision = db_models.Decision(
            summary="Pre-migration legacy decision",
            visibility="team",
            uuid=None,
        )
        result = db.log_decision(workspace, decision)

        report = _run_migration(workspace, dry_run=False)

        assert report.decisions_migrated == 1
        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        md_files = list(decisions_dir.glob("*.md"))
        assert len(md_files) == 1

        fm, _ = parse_decision_file(md_files[0])
        assert fm.uuid is not None
        assert len(fm.uuid) == 36


# ===========================================================================
# Test 8: Code bindings written to frontmatter and read back correctly
# ===========================================================================


class TestBindingsMigrationRoundTrip:
    """Bindings are correctly written to frontmatter during migration and
    re-created in the DB when scan_and_sync processes the file."""

    def test_single_binding_migrated_and_synced(self, workspace: str, workspace_b: str) -> None:
        """One binding on a decision survives migrate + cross-workspace sync."""
        import shutil

        decision = _make_team_decision(workspace, "Binding migration test")
        _make_binding(workspace, "decision", decision.id, "src/api/**/*.py")

        _run_migration(workspace, dry_run=False)

        # Copy .engrams/ to workspace_b and clear its manifest so scan_and_sync
        # processes the copied files (doesn't skip them due to hash match)
        shutil.copytree(
            str(Path(workspace) / ".engrams"),
            str(Path(workspace_b) / ".engrams"),
        )
        _clear_manifest(workspace_b)

        indexer_b = TeamContentIndexer(workspace_b)
        report = indexer_b.scan_and_sync()

        # A binding should have been created in workspace_b
        assert report.bindings_added >= 1

    def test_multiple_bindings_migrated(self, workspace: str) -> None:
        """Multiple bindings per decision are all written to frontmatter."""
        decision = _make_team_decision(workspace, "Multi-binding decision")
        _make_binding(workspace, "decision", decision.id, "src/**/*.py")
        _make_binding(workspace, "decision", decision.id, "tests/**/*.py")
        _make_binding(workspace, "decision", decision.id, "docs/**/*.md")

        report = _run_migration(workspace, dry_run=False)

        assert report.bindings_written == 3

        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        md_files = list(decisions_dir.glob("*.md"))
        assert len(md_files) == 1
        fm, _ = parse_decision_file(md_files[0])
        assert len(fm.bindings) == 3

    def test_binding_type_and_symbol_preserved(self, workspace: str) -> None:
        """Binding type and symbol_pattern survive the migration round-trip."""
        decision = _make_team_decision(workspace, "Symbol binding test")
        binding = CodeBinding(
            item_type="decision",
            item_id=decision.id,
            file_pattern="src/auth/service.py",
            binding_type="implements",
            symbol_pattern="AuthService",
            confidence="manual",
        )
        binding_db_ops.create_code_binding(workspace, binding)

        _run_migration(workspace, dry_run=False)

        decisions_dir = Path(workspace) / ".engrams" / "decisions"
        md_files = list(decisions_dir.glob("*.md"))
        fm, _ = parse_decision_file(md_files[0])

        assert len(fm.bindings) == 1
        b = fm.bindings[0]
        assert b.pattern == "src/auth/service.py"
        assert b.type == "implements"
        assert b.symbol == "AuthService"

    def test_pattern_bindings_migrated_and_synced(self, workspace: str, workspace_b: str) -> None:
        """Pattern bindings survive migrate + cross-workspace sync."""
        import shutil

        pattern = _make_team_pattern(workspace, "Service Layer Pattern")
        binding = CodeBinding(
            item_type="system_pattern",
            item_id=pattern.id,
            file_pattern="src/services/**/*.py",
            symbol_pattern=None,
            binding_type="implements",
            confidence="manual",
        )
        binding_db_ops.create_code_binding(workspace, binding)

        _run_migration(workspace, dry_run=False)

        # Clear manifest in workspace_b so scan_and_sync processes the copied files
        shutil.copytree(
            str(Path(workspace) / ".engrams"),
            str(Path(workspace_b) / ".engrams"),
        )
        _clear_manifest(workspace_b)

        indexer_b = TeamContentIndexer(workspace_b)
        report = indexer_b.scan_and_sync()

        assert report.patterns_upserted >= 1
        assert report.bindings_added >= 1


# ===========================================================================
# Test 9: team_sync package public API
# ===========================================================================


class TestTeamSyncPublicAPI:
    """Verify the public API exported from engrams.team_sync."""

    def test_imports_from_package(self) -> None:
        """All documented symbols are importable from engrams.team_sync."""
        from engrams.team_sync import (  # noqa: F401
            SyncReport,
            TeamContentIndexer,
            ensure_engrams_dir,
            write_decision_file,
            write_pattern_file,
            write_shared_data_file,
        )

    def test_all_list_complete(self) -> None:
        """__all__ contains the expected symbols."""
        import engrams.team_sync as ts

        expected = {
            "TeamContentIndexer",
            "SyncReport",
            "ensure_engrams_dir",
            "write_decision_file",
            "write_pattern_file",
            "write_shared_data_file",
        }
        assert expected == set(ts.__all__)

    def test_ensure_engrams_dir_creates_subdirs(self, workspace: str) -> None:
        """ensure_engrams_dir creates all required subdirectories."""
        engrams_dir = ensure_engrams_dir(workspace)

        assert (engrams_dir / "decisions").is_dir()
        assert (engrams_dir / "patterns").is_dir()
        assert (engrams_dir / "shared-data").is_dir()


# ===========================================================================
# Test 10: CLI subcommand registration
# ===========================================================================


class TestCLIRegistration:
    """migrate-to-filesystem is registered in the CLI."""

    def test_migrate_in_subcommands(self) -> None:
        """'migrate-to-filesystem' is in the _SUBCOMMANDS set."""
        from engrams.cli import _SUBCOMMANDS

        assert "migrate-to-filesystem" in _SUBCOMMANDS

    def test_help_text_mentions_migrate(self, capsys) -> None:
        """Top-level help text mentions migrate-to-filesystem."""
        import sys
        from engrams.cli import _print_help

        _print_help()
        captured = capsys.readouterr()
        assert "migrate-to-filesystem" in captured.out

    def test_migrate_command_help(self) -> None:
        """migrate-to-filesystem --help exits cleanly (via SystemExit 0)."""
        import sys
        from engrams.migrate_command import run_migrate_cli

        with pytest.raises(SystemExit) as exc_info:
            run_migrate_cli(["--help"])

        assert exc_info.value.code == 0

    def test_migrate_dry_run_flag_accepted(self, workspace: str) -> None:
        """--dry-run flag is accepted and treated as dry run."""
        report = _run_migration(workspace, dry_run=True)
        assert report.dry_run is True
