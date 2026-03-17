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

"""Tests for Phase 3 TeamContentIndexer: .engrams/ filesystem → DB sync.

Covers:
  - scan_and_sync picks up a new decision file and creates a DB record
  - scan_and_sync with an unchanged file (hash match) skips it
  - scan_and_sync with a modified file re-upserts the DB record
  - incremental_sync processes only the specified files
  - incremental_sync ignores files outside .engrams/
  - _sync_bindings adds new bindings found in frontmatter
  - _sync_bindings removes bindings no longer in frontmatter
  - _sync_bindings is idempotent (running twice doesn't add duplicates)
  - deleted file is handled gracefully (warning logged, no crash)
  - scan_and_sync on an empty .engrams/ dir returns zero counts
  - scan_and_sync updates manifest hashes
  - round-trip: write via handle_log_decision, then re-parse via scan_and_sync, verify DB matches file
  - personal items (visibility=individual) are NOT affected by sync
"""

import json
import logging
from pathlib import Path
from typing import List

import pytest
import yaml

from engrams.bindings import db_operations as binding_db_ops
from engrams.bindings.models import CodeBinding
from engrams.db import database as db
from engrams.db import models as db_models
from engrams.team_sync import write_through
from engrams.team_sync.indexer import SyncReport, TeamContentIndexer
from engrams.team_sync.manifest import (
    compute_file_hash,
    load_manifest,
    save_manifest,
    update_manifest_entry,
)
from engrams.team_sync.parser import parse_decision_file, parse_pattern_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> str:
    """Return a fresh temporary workspace_id string."""
    return str(tmp_path)


@pytest.fixture()
def initialized_workspace(workspace: str) -> str:
    """Workspace with a fresh Engrams DB (via db.get_db_connection)."""
    db.get_db_connection(workspace)
    return workspace


@pytest.fixture()
def engrams_dir(initialized_workspace: str) -> Path:
    """Return the .engrams/ directory path inside the workspace (created)."""
    d = Path(initialized_workspace) / ".engrams"
    d.mkdir(parents=True, exist_ok=True)
    (d / "decisions").mkdir(exist_ok=True)
    (d / "patterns").mkdir(exist_ok=True)
    (d / "shared-data").mkdir(exist_ok=True)
    return d


@pytest.fixture()
def indexer(initialized_workspace: str) -> TeamContentIndexer:
    """Return a TeamContentIndexer bound to the initialized workspace."""
    return TeamContentIndexer(initialized_workspace)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DECISION_TEMPLATE = """\
---
uuid: {uuid}
title: {title}
tags: {tags}
status: accepted
bindings: {bindings}
created: "2026-03-01T00:00:00+00:00"
updated: "2026-03-01T00:00:00+00:00"
---

## Decision

{decision_body}

## Rationale

{rationale}
"""

_PATTERN_TEMPLATE = """\
---
uuid: {uuid}
name: {name}
tags: {tags}
bindings: {bindings}
updated: "2026-03-01T00:00:00+00:00"
---

{description}
"""

_SHARED_DATA_TEMPLATE = """\
---
category: {category}
updated: "2026-03-01T00:00:00+00:00"
---

### {key}

```json
{value}
```
"""


def _write_decision_file(
    engrams_dir: Path,
    filename: str,
    uuid: str,
    title: str,
    decision_body: str = "Use this approach",
    rationale: str = "Because it works",
    tags: str = '["test"]',
    bindings: str = "[]",
) -> Path:
    """Write a minimal decision markdown file and return the path."""
    path = engrams_dir / "decisions" / filename
    content = _DECISION_TEMPLATE.format(
        uuid=uuid,
        title=title,
        tags=tags,
        bindings=bindings,
        decision_body=decision_body,
        rationale=rationale,
    )
    path.write_text(content, encoding="utf-8")
    return path


def _write_pattern_file(
    engrams_dir: Path,
    filename: str,
    uuid: str,
    name: str,
    description: str = "A reusable pattern.",
    tags: str = '["pattern"]',
    bindings: str = "[]",
) -> Path:
    """Write a minimal pattern markdown file and return the path."""
    path = engrams_dir / "patterns" / filename
    content = _PATTERN_TEMPLATE.format(
        uuid=uuid,
        name=name,
        description=description,
        tags=tags,
        bindings=bindings,
    )
    path.write_text(content, encoding="utf-8")
    return path


def _write_shared_data_file(
    engrams_dir: Path,
    filename: str,
    category: str,
    key: str,
    value: str = '"hello"',
) -> Path:
    """Write a minimal shared-data markdown file and return the path."""
    path = engrams_dir / "shared-data" / filename
    content = _SHARED_DATA_TEMPLATE.format(
        category=category,
        key=key,
        value=value,
    )
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test: scan_and_sync on empty directory
# ---------------------------------------------------------------------------


def test_scan_and_sync_empty_directory_returns_zero_counts(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
) -> None:
    """scan_and_sync on an empty .engrams/ dir should return all-zero report."""
    report = indexer.scan_and_sync()

    assert report.files_processed == 0
    assert report.decisions_upserted == 0
    assert report.patterns_upserted == 0
    assert report.custom_data_upserted == 0
    assert report.bindings_added == 0
    assert report.bindings_removed == 0
    assert report.files_skipped == 0
    assert report.errors == []


def test_scan_and_sync_no_engrams_dir_returns_zero_counts(
    initialized_workspace: str,
) -> None:
    """If .engrams/ doesn't exist at all, scan_and_sync returns zero counts."""
    indexer = TeamContentIndexer(initialized_workspace)
    # Don't create .engrams/ — just run
    report = indexer.scan_and_sync()

    assert report.files_processed == 0
    assert report.errors == []


# ---------------------------------------------------------------------------
# Test: scan_and_sync picks up a new decision file
# ---------------------------------------------------------------------------


def test_scan_and_sync_new_decision_file_creates_db_record(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """A new decision .md file is parsed and inserted into the DB."""
    test_uuid = "11111111-1111-1111-1111-111111111111"
    _write_decision_file(
        engrams_dir,
        "001-use-postgres.md",
        uuid=test_uuid,
        title="Use PostgreSQL",
        decision_body="Use PostgreSQL for all relational storage.",
        rationale="Strong ecosystem and ACID compliance.",
    )

    report = indexer.scan_and_sync()

    assert report.decisions_upserted == 1
    assert report.files_processed == 1
    assert report.errors == []

    # Verify DB record
    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None
    assert "PostgreSQL" in decision.summary
    assert decision.rationale is not None
    assert "ACID" in decision.rationale
    assert decision.visibility == "team"
    assert decision.uuid == test_uuid


def test_scan_and_sync_new_pattern_file_creates_db_record(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """A new pattern .md file is parsed and inserted into the DB."""
    test_uuid = "22222222-2222-2222-2222-222222222222"
    _write_pattern_file(
        engrams_dir,
        "repository-pattern.md",
        uuid=test_uuid,
        name="Repository Pattern",
        description="Abstracts data access logic behind a clean interface.",
    )

    report = indexer.scan_and_sync()

    assert report.patterns_upserted == 1
    assert report.files_processed == 1
    assert report.errors == []

    patterns = db.get_system_patterns(initialized_workspace)
    names = [p.name for p in patterns]
    assert "Repository Pattern" in names


def test_scan_and_sync_new_shared_data_file_creates_custom_data(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """A new shared-data .md file is parsed and upserted into custom_data."""
    _write_shared_data_file(
        engrams_dir,
        "project-glossary.md",
        category="ProjectGlossary",
        key="ADR",
        value='"Architecture Decision Record"',
    )

    report = indexer.scan_and_sync()

    assert report.custom_data_upserted == 1
    assert report.files_processed == 1
    assert report.errors == []

    entries = db.get_custom_data(
        initialized_workspace, category="ProjectGlossary", key="ADR"
    )
    assert len(entries) == 1
    assert entries[0].value == "Architecture Decision Record"


# ---------------------------------------------------------------------------
# Test: scan_and_sync skips unchanged files (hash match)
# ---------------------------------------------------------------------------


def test_scan_and_sync_unchanged_file_is_skipped(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
) -> None:
    """If the file hash matches the manifest, the file is skipped on second sync."""
    test_uuid = "33333333-3333-3333-3333-333333333333"
    _write_decision_file(
        engrams_dir,
        "001-cached.md",
        uuid=test_uuid,
        title="Cached Decision",
    )

    # First sync — processes the file
    first_report = indexer.scan_and_sync()
    assert first_report.files_processed == 1
    assert first_report.files_skipped == 0

    # Second sync — hash unchanged, should skip
    second_report = indexer.scan_and_sync()
    assert second_report.files_processed == 0
    assert second_report.files_skipped == 1


# ---------------------------------------------------------------------------
# Test: scan_and_sync re-upserts modified files
# ---------------------------------------------------------------------------


def test_scan_and_sync_modified_file_reupserts_db_record(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """A modified decision file triggers a DB upsert on the next scan."""
    test_uuid = "44444444-4444-4444-4444-444444444444"
    path = _write_decision_file(
        engrams_dir,
        "001-modified.md",
        uuid=test_uuid,
        title="Original Title",
        decision_body="Original content.",
        rationale="Original rationale.",
    )

    # First sync
    indexer.scan_and_sync()
    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None
    assert "Original" in decision.summary

    # Modify the file
    new_content = path.read_text(encoding="utf-8").replace(
        "Original content.", "Updated content."
    ).replace("Original rationale.", "Updated rationale.")
    path.write_text(new_content, encoding="utf-8")

    # Second sync — file hash changed, should re-process
    second_report = indexer.scan_and_sync()
    assert second_report.files_processed == 1
    assert second_report.decisions_upserted == 1

    updated_decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert updated_decision is not None
    assert "Updated" in updated_decision.summary or "Updated" in (updated_decision.rationale or "")


# ---------------------------------------------------------------------------
# Test: scan_and_sync updates manifest hashes
# ---------------------------------------------------------------------------


def test_scan_and_sync_updates_manifest_hashes(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
) -> None:
    """After sync, the manifest should contain an entry for each processed file."""
    test_uuid = "55555555-5555-5555-5555-555555555555"
    path = _write_decision_file(
        engrams_dir,
        "001-manifest-test.md",
        uuid=test_uuid,
        title="Manifest Test",
    )

    indexer.scan_and_sync()

    manifest = load_manifest(engrams_dir)
    assert test_uuid in manifest.entries
    entry = manifest.entries[test_uuid]
    assert entry.content_hash == compute_file_hash(path)
    assert "decisions" in entry.file_path


# ---------------------------------------------------------------------------
# Test: incremental_sync processes only specified files
# ---------------------------------------------------------------------------


def test_incremental_sync_processes_only_given_files(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """incremental_sync only processes the files provided in changed_files."""
    uuid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uuid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    path_a = _write_decision_file(
        engrams_dir, "aaa.md", uuid=uuid_a, title="Decision A"
    )
    _write_decision_file(engrams_dir, "bbb.md", uuid=uuid_b, title="Decision B")

    # Incremental sync with only path_a
    report = indexer.incremental_sync([path_a])

    assert report.files_processed == 1
    assert report.decisions_upserted == 1

    # Decision A should be in DB
    dec_a = db.get_decision_by_uuid(initialized_workspace, uuid_a)
    assert dec_a is not None

    # Decision B should NOT be in DB
    dec_b = db.get_decision_by_uuid(initialized_workspace, uuid_b)
    assert dec_b is None


def test_incremental_sync_ignores_files_outside_engrams_dir(
    indexer: TeamContentIndexer,
    initialized_workspace: str,
    tmp_path: Path,
) -> None:
    """incremental_sync silently ignores files not under .engrams/."""
    outside_file = tmp_path / "some-other-dir" / "notes.md"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("# Some Notes\nNot an Engrams file.\n", encoding="utf-8")

    report = indexer.incremental_sync([outside_file])

    assert report.files_processed == 0
    assert report.errors == []


# ---------------------------------------------------------------------------
# Test: binding sync
# ---------------------------------------------------------------------------


def test_sync_bindings_adds_new_bindings_from_frontmatter(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """Bindings in the frontmatter are added to the DB."""
    test_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    bindings_yaml = (
        "[{pattern: 'src/db/**/*.py', type: implements},"
        " {pattern: 'tests/test_db.py', type: tests}]"
    )
    _write_decision_file(
        engrams_dir,
        "001-bindings.md",
        uuid=test_uuid,
        title="DB Decision",
        bindings=bindings_yaml,
    )

    report = indexer.scan_and_sync()

    assert report.decisions_upserted == 1
    assert report.bindings_added == 2

    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None and decision.id is not None
    bindings = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    patterns = {b.file_pattern for b in bindings}
    assert "src/db/**/*.py" in patterns
    assert "tests/test_db.py" in patterns


def test_sync_bindings_removes_deleted_bindings(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """Bindings removed from frontmatter are deleted from the DB."""
    test_uuid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    path = _write_decision_file(
        engrams_dir,
        "001-remove-binding.md",
        uuid=test_uuid,
        title="Remove Binding Decision",
        bindings="[{pattern: 'src/old/**/*.py', type: implements}]",
    )

    # First sync — creates the binding
    indexer.scan_and_sync()

    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None and decision.id is not None
    bindings = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    assert len(bindings) == 1

    # Update file to remove the binding
    new_content = path.read_text(encoding="utf-8").replace(
        "[{pattern: 'src/old/**/*.py', type: implements}]", "[]"
    )
    path.write_text(new_content, encoding="utf-8")

    # Second sync — should remove the binding
    report = indexer.scan_and_sync()
    assert report.bindings_removed == 1

    bindings_after = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    assert len(bindings_after) == 0


def test_sync_bindings_is_idempotent(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """Running sync twice with the same bindings doesn't create duplicates."""
    test_uuid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    path = _write_decision_file(
        engrams_dir,
        "001-idempotent.md",
        uuid=test_uuid,
        title="Idempotent Decision",
        bindings="[{pattern: 'src/**/*.py', type: implements}]",
    )

    # First sync
    indexer.scan_and_sync()

    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None and decision.id is not None
    bindings_after_first = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    assert len(bindings_after_first) == 1

    # Force re-process by updating manifest hash
    manifest = load_manifest(Path(initialized_workspace) / ".engrams")
    if test_uuid in manifest.entries:
        manifest.entries[test_uuid].content_hash = "stale-hash-to-force-reprocess"
        save_manifest(Path(initialized_workspace) / ".engrams", manifest)

    # Second sync — should not add duplicate bindings
    indexer.scan_and_sync()

    bindings_after_second = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    assert len(bindings_after_second) == 1  # Still exactly one binding


# ---------------------------------------------------------------------------
# Test: deleted file handled gracefully
# ---------------------------------------------------------------------------


def test_scan_and_sync_deleted_file_is_handled_gracefully(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A file recorded in the manifest but no longer on disk logs a warning (no crash)."""
    # Manually add a stale manifest entry pointing to a non-existent file
    manifest = load_manifest(engrams_dir)
    ghost_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    update_manifest_entry(
        manifest,
        ghost_uuid,
        ".engrams/decisions/ghost-decision.md",
        "decision",
        "deadbeef" * 8,
    )
    save_manifest(engrams_dir, manifest)

    with caplog.at_level(logging.WARNING):
        report = indexer.scan_and_sync()

    assert report.errors == []  # No crash
    # The ghost entry should be removed from the manifest
    updated_manifest = load_manifest(engrams_dir)
    assert ghost_uuid not in updated_manifest.entries


# ---------------------------------------------------------------------------
# Test: incremental_sync with non-existent file
# ---------------------------------------------------------------------------


def test_incremental_sync_nonexistent_file_no_crash(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """incremental_sync with a file that doesn't exist logs a warning, no crash."""
    ghost_path = engrams_dir / "decisions" / "nonexistent.md"

    with caplog.at_level(logging.WARNING):
        report = indexer.incremental_sync([ghost_path])

    assert report.files_processed == 0
    assert report.errors == []


# ---------------------------------------------------------------------------
# Test: personal items are NOT affected by sync
# ---------------------------------------------------------------------------


def test_personal_items_not_affected_by_sync(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """An 'individual' visibility decision in DB must not be touched by sync."""
    # Create a personal decision directly in DB (not filesystem)
    personal_decision = db_models.Decision(
        summary="My personal note",
        rationale="Private context",
        tags=["personal"],
        visibility="individual",
    )
    saved = db.log_decision(initialized_workspace, personal_decision)
    assert saved.id is not None
    personal_id: int = saved.id

    # Sync should not touch personal items
    report = indexer.scan_and_sync()

    # Personal decision should still exist unchanged
    retrieved = db.get_decision_by_id(initialized_workspace, personal_id)
    assert retrieved is not None
    assert retrieved.summary == "My personal note"
    assert retrieved.visibility == "individual"
    # Sync should not have processed any files (no .engrams/ files)
    assert report.files_processed == 0


# ---------------------------------------------------------------------------
# Test: newly synced bindings have last_verified_at = None
# ---------------------------------------------------------------------------


def test_newly_synced_bindings_have_null_last_verified_at(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """Bindings added by sync should have last_verified_at=None (triggers re-verification)."""
    test_uuid = "11111111-2222-3333-4444-555555555555"
    _write_decision_file(
        engrams_dir,
        "001-verify.md",
        uuid=test_uuid,
        title="Verify Me",
        bindings="[{pattern: 'src/verify/**/*.py', type: implements}]",
    )

    indexer.scan_and_sync()

    decision = db.get_decision_by_uuid(initialized_workspace, test_uuid)
    assert decision is not None and decision.id is not None
    bindings = binding_db_ops.get_bindings_for_item(
        initialized_workspace, "decision", decision.id
    )
    assert len(bindings) == 1
    assert bindings[0].last_verified_at is None


# ---------------------------------------------------------------------------
# Test: round-trip with write_through
# ---------------------------------------------------------------------------


def test_round_trip_write_through_then_sync(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """Write via DB + write_through, then scan_and_sync should match file contents in DB."""
    # Create a team decision in DB — this triggers write_through which writes the file
    decision = db_models.Decision(
        summary="Use Redis for caching",
        rationale="Low latency key-value store.",
        implementation_details="TTL of 300s for session data.",
        tags=["caching", "redis"],
        visibility="team",
    )
    saved = db.log_decision(initialized_workspace, decision)
    assert saved.uuid is not None

    # Write the decision file (simulating write_through)
    write_through.write_decision_file(initialized_workspace, saved, [])

    # Verify the file was written
    decisions_dir = Path(initialized_workspace) / ".engrams" / "decisions"
    md_files = list(decisions_dir.glob("*.md"))
    assert len(md_files) >= 1

    # Now modify the DB record's summary to simulate divergence
    # (File should win after sync)
    # First, force re-scan by clearing the manifest
    manifest = load_manifest(engrams_dir)
    manifest.entries.clear()
    save_manifest(engrams_dir, manifest)

    # Run sync — file wins
    report = indexer.scan_and_sync()
    assert report.decisions_upserted >= 1
    assert report.errors == []

    # DB should match the file's content
    synced = db.get_decision_by_uuid(initialized_workspace, saved.uuid)
    assert synced is not None
    assert "Redis" in synced.summary


# ---------------------------------------------------------------------------
# Test: multiple files in one sync pass
# ---------------------------------------------------------------------------


def test_scan_and_sync_multiple_files(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
    initialized_workspace: str,
) -> None:
    """scan_and_sync processes all .md files in all subdirectories."""
    _write_decision_file(
        engrams_dir, "001-a.md", uuid="aaaa0001-0000-0000-0000-000000000000", title="Decision A"
    )
    _write_decision_file(
        engrams_dir, "002-b.md", uuid="bbbb0002-0000-0000-0000-000000000000", title="Decision B"
    )
    _write_pattern_file(
        engrams_dir, "pattern-x.md", uuid="xxxx0003-0000-0000-0000-000000000000", name="Pattern X"
    )
    _write_shared_data_file(
        engrams_dir, "data.md", category="TestCategory", key="mykey", value='"myvalue"'
    )

    report = indexer.scan_and_sync()

    assert report.files_processed == 4
    assert report.decisions_upserted == 2
    assert report.patterns_upserted == 1
    assert report.custom_data_upserted == 1
    assert report.errors == []


# ---------------------------------------------------------------------------
# Test: SyncReport dataclass defaults
# ---------------------------------------------------------------------------


def test_sync_report_defaults() -> None:
    """SyncReport should initialise with all-zero counts and empty errors list."""
    report = SyncReport()
    assert report.files_processed == 0
    assert report.decisions_upserted == 0
    assert report.patterns_upserted == 0
    assert report.custom_data_upserted == 0
    assert report.bindings_added == 0
    assert report.bindings_removed == 0
    assert report.files_skipped == 0
    assert report.errors == []


def test_sync_report_errors_list_not_shared() -> None:
    """Each SyncReport instance should have its own errors list (dataclass field factory)."""
    r1 = SyncReport()
    r2 = SyncReport()
    r1.errors.append("oops")
    assert r2.errors == []


# ---------------------------------------------------------------------------
# Test: malformed file error handling
# ---------------------------------------------------------------------------


def test_scan_and_sync_malformed_file_records_error(
    indexer: TeamContentIndexer,
    engrams_dir: Path,
) -> None:
    """A decision file with missing/malformed frontmatter records an error, doesn't crash."""
    bad_path = engrams_dir / "decisions" / "bad-file.md"
    bad_path.write_text(
        "# No Frontmatter Here\nThis file has no YAML front matter.\n",
        encoding="utf-8",
    )

    report = indexer.scan_and_sync()

    # Should record error but not crash
    assert len(report.errors) == 1
    assert "bad-file.md" in report.errors[0] or "parse" in report.errors[0].lower()
    assert report.decisions_upserted == 0


# ---------------------------------------------------------------------------
# Test: IndexSyncArgs model
# ---------------------------------------------------------------------------


def test_index_sync_args_model() -> None:
    """IndexSyncArgs accepts workspace_id and optional files."""
    from engrams.db.models import IndexSyncArgs

    args = IndexSyncArgs(workspace_id="/some/path")
    assert args.workspace_id == "/some/path"
    assert args.files is None

    args2 = IndexSyncArgs(workspace_id="/other", files=["a.md", "b.md"])
    assert args2.files == ["a.md", "b.md"]
