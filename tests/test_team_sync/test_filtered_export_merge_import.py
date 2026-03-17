"""
Tests for team-sync features:
  - Filtered export (visibility_filter='team')
  - Merge import (merge=True skips existing decisions / patterns / custom data)
  - Content-hash slugs used as dedup keys for decisions

These are integration-style tests that exercise the full handler layer
against a real (temporary) Engrams SQLite database.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — import the handler layer and models
# ---------------------------------------------------------------------------
import sys

# Allow the test to be run from the repo root without installing the package
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from engrams.db import models
from engrams.handlers import mcp_handlers
from engrams.handlers.mcp_handlers import _decision_slug, _existing_decision_uuids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> str:
    """Return the path of a fresh temporary workspace."""
    ws = str(tmp_path)
    # Ensure the engrams DB directory exists (the DB is lazily created on
    # first use, but the directory must exist for the test helpers)
    (tmp_path / "engrams").mkdir(parents=True, exist_ok=True)
    return ws


def _log_decision(workspace_id: str, summary: str, visibility: str = "team") -> dict:
    args = models.LogDecisionArgs(
        workspace_id=workspace_id,
        summary=summary,
        rationale="test rationale",
        visibility=visibility,
    )
    return mcp_handlers.handle_log_decision(args)


def _log_pattern(workspace_id: str, name: str, visibility: str = "team") -> None:
    args = models.LogSystemPatternArgs(
        workspace_id=workspace_id,
        name=name,
        description="test description",
        visibility=visibility,
    )
    mcp_handlers.handle_log_system_pattern(args)


def _log_custom(workspace_id: str, category: str, key: str, value: str, visibility: str = "team") -> None:
    args = models.LogCustomDataArgs(
        workspace_id=workspace_id,
        category=category,
        key=key,
        value=value,
        visibility=visibility,
    )
    mcp_handlers.handle_log_custom_data(args)


def _export(workspace_id: str, output_path: str, visibility_filter: str | None = None) -> dict:
    args = models.ExportEngramsToMarkdownArgs(
        workspace_id=workspace_id,
        output_path=output_path,
        visibility_filter=visibility_filter,
    )
    return mcp_handlers.handle_export_engrams_to_markdown(args)


def _import(workspace_id: str, input_path: str, merge: bool = False) -> dict:
    args = models.ImportMarkdownToEngramsArgs(
        workspace_id=workspace_id,
        input_path=input_path,
        merge=merge,
    )
    return mcp_handlers.handle_import_markdown_to_engrams(args)


def _get_decisions(workspace_id: str) -> list:
    args = models.GetDecisionsArgs(workspace_id=workspace_id)
    return mcp_handlers.handle_get_decisions(args)


def _get_patterns(workspace_id: str) -> list:
    args = models.GetSystemPatternsArgs(workspace_id=workspace_id)
    return mcp_handlers.handle_get_system_patterns(args)


def _get_custom(workspace_id: str) -> list:
    args = models.GetCustomDataArgs(workspace_id=workspace_id)
    return mcp_handlers.handle_get_custom_data(args)


# ===========================================================================
# Tests — slug helper
# ===========================================================================


def test_decision_slug_is_stable():
    """The same summary always produces the same 12-char hex slug."""
    s1 = _decision_slug("Use PostgreSQL for production")
    s2 = _decision_slug("Use PostgreSQL for production")
    assert s1 == s2
    assert len(s1) == 12
    assert s1.isalnum()


def test_decision_slug_case_insensitive():
    """Slug is insensitive to leading/trailing whitespace and case."""
    s1 = _decision_slug("  Use PostgreSQL  ")
    s2 = _decision_slug("use postgresql")
    assert s1 == s2


def test_decision_slug_differs_for_different_summaries():
    s1 = _decision_slug("Decision A")
    s2 = _decision_slug("Decision B")
    assert s1 != s2


# ===========================================================================
# Tests — UUID stability
# ===========================================================================


def test_log_decision_generates_uuid(workspace):
    """Every logged decision must receive a non-empty UUID."""
    result = _log_decision(workspace, "UUID test decision", visibility="team")
    assert result.get("uuid"), "log_decision must return a uuid"


def test_log_decision_uuid_is_stable_across_re_fetch(workspace):
    """The UUID stored on insert must be retrievable via get_decisions."""
    _log_decision(workspace, "Stable UUID decision", visibility="team")
    decisions = _get_decisions(workspace)
    match = [d for d in decisions if "Stable UUID decision" in d.get("summary", "")]
    assert match, "Decision not found"
    assert match[0].get("uuid"), "Retrieved decision must carry a uuid"


# ===========================================================================
# Tests — filtered export
# ===========================================================================


def test_filtered_export_includes_only_team_decisions(workspace, tmp_path):
    """visibility_filter='team' must exclude 'individual' decisions."""
    _log_decision(workspace, "Team decision alpha", visibility="team")
    _log_decision(workspace, "Individual note beta", visibility="individual")

    export_dir = str(tmp_path / "export")
    result = _export(workspace, output_path=export_dir, visibility_filter="team")

    assert result["status"] == "success"
    assert result["visibility_filter"] == "team"

    decision_md = Path(export_dir) / "decision_log.md"
    assert decision_md.exists(), "decision_log.md should be created"
    content = decision_md.read_text()
    assert "Team decision alpha" in content
    assert "Individual note beta" not in content


def test_filtered_export_includes_only_team_patterns(workspace, tmp_path):
    """visibility_filter='team' must exclude 'individual' patterns."""
    _log_pattern(workspace, "Team Pattern X", visibility="team")
    _log_pattern(workspace, "Individual Pattern Y", visibility="individual")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    patterns_md = Path(export_dir) / "system_patterns.md"
    assert patterns_md.exists()
    content = patterns_md.read_text()
    assert "Team Pattern X" in content
    assert "Individual Pattern Y" not in content


def test_filtered_export_excludes_context_and_progress(workspace, tmp_path):
    """Filtered export should NOT write product_context.md, active_context.md, progress_log.md."""
    _log_decision(workspace, "A team decision", visibility="team")
    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    export_path = Path(export_dir)
    assert not (export_path / "product_context.md").exists()
    assert not (export_path / "active_context.md").exists()
    assert not (export_path / "progress_log.md").exists()


def test_unfiltered_export_includes_all_visibility_levels(workspace, tmp_path):
    """Without visibility_filter, all visibility levels are exported."""
    _log_decision(workspace, "Team decision", visibility="team")
    _log_decision(workspace, "Individual decision", visibility="individual")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter=None)

    decision_md = Path(export_dir) / "decision_log.md"
    content = decision_md.read_text()
    assert "Team decision" in content
    assert "Individual decision" in content


def test_filtered_export_custom_data(workspace, tmp_path):
    """visibility_filter='team' filters custom_data by visibility."""
    _log_custom(workspace, "ADR", "db-choice", "postgres", visibility="team")
    _log_custom(workspace, "ADR", "private-note", "my note", visibility="individual")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    adr_file = Path(export_dir) / "custom_data" / "ADR.md"
    assert adr_file.exists()
    content = adr_file.read_text()
    assert "db-choice" in content
    assert "private-note" not in content


# ===========================================================================
# Tests — merge import
# ===========================================================================


def test_merge_import_upserts_modified_decision(workspace, tmp_path):
    """In merge mode, editing a decision's text in the markdown then importing
    must UPDATE the existing row (upsert), not create a duplicate."""
    _log_decision(workspace, "Original summary text", visibility="team")

    # Export
    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    # Mutate the summary in the exported markdown
    decision_md = (tmp_path / "export" / "decision_log.md")
    original_text = decision_md.read_text()
    modified_text = original_text.replace("Original summary text", "Updated summary text")
    decision_md.write_text(modified_text)

    # Import back in merge mode
    result = _import(workspace, input_path=export_dir, merge=True)
    logged = result.get("items_logged", {})
    assert logged.get("decision_log", 0) >= 1, "Upsert should count as logged"

    # Exactly ONE decision should exist and it must have the updated summary
    decisions = _get_decisions(workspace)
    all_summaries = [d["summary"] for d in decisions]
    assert not any("Original summary text" in s for s in all_summaries), (
        "Old summary should be gone after upsert"
    )
    assert any("Updated summary text" in s for s in all_summaries), (
        "New summary must be present after upsert"
    )
    assert len(decisions) == 1, f"Expected 1 decision, got {len(decisions)}: {all_summaries}"


def test_merge_import_skips_existing_decision(workspace, tmp_path):
    """In merge mode a decision already in the DB is not duplicated."""
    _log_decision(workspace, "Existing team decision", visibility="team")

    # Export to a temp directory
    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    # Import back in merge mode — decision already exists (same UUID, same text)
    # The upsert path still updates in place, so no net-new row is added.
    result = _import(workspace, input_path=export_dir, merge=True)
    assert result["merge"] is True

    # Confirm no duplicate in the DB
    decisions = _get_decisions(workspace)
    summaries = [d["summary"] for d in decisions]
    assert summaries.count("Existing team decision") == 1


def test_merge_import_adds_new_decision(workspace, tmp_path):
    """In merge mode a decision NOT yet in the DB is inserted."""
    # Start with workspace B (clean) — export from workspace A
    ws_a = workspace
    ws_b = str(tmp_path / "ws_b")
    (tmp_path / "ws_b" / "engrams").mkdir(parents=True, exist_ok=True)

    _log_decision(ws_a, "New team decision from A", visibility="team")
    export_dir = str(tmp_path / "export")
    _export(ws_a, output_path=export_dir, visibility_filter="team")

    # Import into B
    result = _import(ws_b, input_path=export_dir, merge=True)
    logged = result.get("items_logged", {})
    assert logged.get("decision_log", 0) >= 1

    decisions_in_b = _get_decisions(ws_b)
    summaries = [d["summary"] for d in decisions_in_b]
    # The parsed summary may include inline markdown formatting from the export round-trip;
    # check that at least one entry starts with the expected text.
    assert any("New team decision from A" in s for s in summaries)


def test_merge_import_does_not_overwrite_personal_context(workspace, tmp_path):
    """Merge mode must skip product_context.md and active_context.md."""
    # Set personal product context
    update_args = models.UpdateContextArgs(
        workspace_id=workspace,
        content={"project_name": "My Personal Project"},
    )
    mcp_handlers.handle_update_product_context(update_args)

    # Create an export dir that contains a product_context.md with different content
    export_dir = Path(tmp_path / "export")
    export_dir.mkdir(parents=True)
    (export_dir / "product_context.md").write_text(
        "# Product Context\n\n## Project Name\nTeam Project\n", encoding="utf-8"
    )
    # Also add a decision so the import has something to do
    _log_decision(workspace, "Some team decision", visibility="team")
    full_export_dir = str(tmp_path / "full_export")
    _export(workspace, output_path=full_export_dir, visibility_filter="team")
    # Copy the product_context.md into the full_export dir to test it's skipped
    import shutil
    shutil.copy(str(export_dir / "product_context.md"), full_export_dir)

    result = _import(workspace, input_path=full_export_dir, merge=True)
    skipped = result.get("items_skipped", {})
    assert "product_context.md" in skipped

    # Personal product context must be unchanged.
    # handle_get_product_context returns the content dict directly (no {"content": ...} wrapper)
    ctx = mcp_handlers.handle_get_product_context(
        models.GetContextArgs(workspace_id=workspace)
    )
    assert ctx.get("project_name") == "My Personal Project"


def test_merge_import_skips_existing_pattern(workspace, tmp_path):
    """In merge mode a system pattern with the same name is not duplicated."""
    _log_pattern(workspace, "Repository Pattern", visibility="team")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    result = _import(workspace, input_path=export_dir, merge=True)
    skipped = result.get("items_skipped", {})
    assert skipped.get("system_patterns", 0) >= 1

    patterns = _get_patterns(workspace)
    names = [p["name"] for p in patterns]
    assert names.count("Repository Pattern") == 1


def test_merge_import_skips_existing_custom_data(workspace, tmp_path):
    """In merge mode a custom_data entry with the same category+key is skipped."""
    # Use an underscore-free category name so the round-trip export→import doesn't
    # rename it (the export uses the category as-is for the file heading, while the
    # import reconstructs the category from the filename stem with `replace("_", " ")`).
    _log_custom(workspace, "Config", "db-url", "postgres://localhost/mydb", visibility="team")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    result = _import(workspace, input_path=export_dir, merge=True)
    skipped = result.get("items_skipped", {})
    assert skipped.get("custom_data", 0) >= 1, (
        f"Expected at least 1 skipped custom_data entry, got {skipped}. "
        f"Full report: {result}"
    )

    custom = _get_custom(workspace)
    matches = [e for e in custom if e["key"] == "db-url"]
    assert len(matches) == 1


def test_non_merge_import_overwrites(workspace, tmp_path):
    """Without merge=True the original overwrite behaviour is preserved."""
    _log_decision(workspace, "Original decision", visibility="team")

    export_dir = str(tmp_path / "export")
    _export(workspace, output_path=export_dir, visibility_filter="team")

    # Non-merge import should not skip
    result = _import(workspace, input_path=export_dir, merge=False)
    assert result["merge"] is False
    # items_skipped should be empty for decisions in non-merge mode
    skipped = result.get("items_skipped", {})
    assert skipped.get("decision_log", 0) == 0


# ===========================================================================
# Tests — install-hooks command
# ===========================================================================


def test_install_hooks_creates_hook_files(tmp_path):
    """install-hooks should write executable pre-commit and post-merge files."""
    # Set up a fake Git repo structure
    git_dir = tmp_path / ".git"
    (git_dir / "hooks").mkdir(parents=True)

    from engrams.install_hooks_command import run_install_hooks_cli

    run_install_hooks_cli(sys_args=["--project-dir", str(tmp_path)])

    pre_commit = git_dir / "hooks" / "pre-commit"
    post_merge = git_dir / "hooks" / "post-merge"

    assert pre_commit.exists()
    assert post_merge.exists()

    # Both hooks should be executable
    import stat as stat_mod

    assert pre_commit.stat().st_mode & stat_mod.S_IXUSR
    assert post_merge.stat().st_mode & stat_mod.S_IXUSR


def test_install_hooks_content(tmp_path):
    """Hook files should reference the correct export-dir (legacy mode)."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    from engrams.install_hooks_command import run_install_hooks_cli

    run_install_hooks_cli(
        sys_args=[
            "--project-dir", str(tmp_path),
            "--export-dir", "team-engrams",
            "--mode", "legacy",
        ]
    )

    pre_commit = (tmp_path / ".git" / "hooks" / "pre-commit").read_text()
    post_merge = (tmp_path / ".git" / "hooks" / "post-merge").read_text()

    assert "team-engrams" in pre_commit
    assert "team-engrams" in post_merge
    assert "visibility-filter team" in pre_commit
    assert "--merge" in post_merge


def test_install_hooks_content_filesystem_mode(tmp_path):
    """Filesystem-first mode (default) uses index-sync in post-merge hook."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    from engrams.install_hooks_command import run_install_hooks_cli

    run_install_hooks_cli(
        sys_args=["--project-dir", str(tmp_path), "--export-dir", "team-engrams"]
    )

    pre_commit = (tmp_path / ".git" / "hooks" / "pre-commit").read_text()
    post_merge = (tmp_path / ".git" / "hooks" / "post-merge").read_text()

    # Pre-commit still exports team data
    assert "team-engrams" in pre_commit
    assert "visibility-filter team" in pre_commit

    # Post-merge uses index-sync, not import
    assert "index-sync" in post_merge
    assert ".engrams/" in post_merge
    # Legacy --merge flag should NOT be in new-style hook
    assert "--merge" not in post_merge


def test_install_hooks_does_not_overwrite_without_force(tmp_path):
    """Without --force, existing hook files must not be overwritten."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text("#!/bin/sh\necho custom hook\n")

    from engrams.install_hooks_command import run_install_hooks_cli

    run_install_hooks_cli(sys_args=["--project-dir", str(tmp_path)])

    # Content should be unchanged
    assert pre_commit.read_text() == "#!/bin/sh\necho custom hook\n"


def test_install_hooks_force_overwrites(tmp_path):
    """--force should overwrite existing hook files."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text("#!/bin/sh\necho custom hook\n")

    from engrams.install_hooks_command import run_install_hooks_cli

    run_install_hooks_cli(sys_args=["--project-dir", str(tmp_path), "--force"])

    content = pre_commit.read_text()
    assert "Engrams pre-commit hook" in content


def test_install_hooks_fails_gracefully_without_git(tmp_path):
    """install-hooks should exit with code 1 if .git dir is missing."""
    from engrams.install_hooks_command import run_install_hooks_cli

    with pytest.raises(SystemExit) as exc_info:
        run_install_hooks_cli(sys_args=["--project-dir", str(tmp_path)])
    assert exc_info.value.code == 1
