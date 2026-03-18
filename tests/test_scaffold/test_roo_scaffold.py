"""Tests for the Roo scaffold installer (engrams init --tool roo)."""

import shutil

import pytest

from engrams.init_command import (
    TOOL_REGISTRY,
    _ROO_SCAFFOLD_FILES,
    _install_roo_scaffold,
    get_scaffolds_dir,
    list_tools,
)


class TestGetScaffoldsDir:
    """Tests for get_scaffolds_dir()."""

    def test_get_scaffolds_dir(self):
        """get_scaffolds_dir() returns a Path that exists and contains roo/ subdirectory."""
        scaffolds = get_scaffolds_dir()
        assert scaffolds.exists(), f"Scaffolds directory does not exist: {scaffolds}"
        assert scaffolds.is_dir(), f"Scaffolds path is not a directory: {scaffolds}"

        roo_dir = scaffolds / "roo"
        assert roo_dir.exists(), f"roo/ subdirectory does not exist: {roo_dir}"
        assert roo_dir.is_dir(), f"roo/ path is not a directory: {roo_dir}"


class TestRooScaffoldFilesExist:
    """Tests that all scaffold source files are present in the package."""

    def test_roo_scaffold_files_exist(self):
        """All 6 files in _ROO_SCAFFOLD_FILES exist in get_scaffolds_dir() / 'roo'."""
        roo_dir = get_scaffolds_dir() / "roo"
        assert len(_ROO_SCAFFOLD_FILES) == 6, (
            f"Expected 6 scaffold files, got {len(_ROO_SCAFFOLD_FILES)}"
        )
        for src_name in _ROO_SCAFFOLD_FILES:
            src_path = roo_dir / src_name
            assert src_path.exists(), f"Scaffold source file missing: {src_path}"
            assert src_path.stat().st_size > 0, (
                f"Scaffold source file is empty: {src_path}"
            )


class TestInstallRooScaffoldFresh:
    """Tests installing scaffold into an empty directory."""

    def test_install_roo_scaffold_fresh(self, tmp_path):
        """Install into an empty tmp_path, verify all 6 output files are created and non-empty."""
        results = _install_roo_scaffold(tmp_path)

        assert len(results) == 6, f"Expected 6 results, got {len(results)}: {results}"

        for _src_name, dest_relpath in _ROO_SCAFFOLD_FILES.items():
            dest = tmp_path / dest_relpath
            assert dest.exists(), f"Expected file not created: {dest_relpath}"
            assert dest.stat().st_size > 0, f"Installed file is empty: {dest_relpath}"

        # All results should indicate "installed"
        for r in results:
            assert "installed" in r, f"Unexpected result: {r}"


class TestInstallRooScaffoldIdenticalSkip:
    """Tests that identical files are skipped."""

    def test_install_roo_scaffold_identical_skip(self, tmp_path):
        """Pre-populate dest with identical copies, verify 'already up to date' for each."""
        roo_dir = get_scaffolds_dir() / "roo"

        # Pre-populate with identical copies
        for src_name, dest_relpath in _ROO_SCAFFOLD_FILES.items():
            src_path = roo_dir / src_name
            dest_path = tmp_path / dest_relpath
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_path), str(dest_path))

        results = _install_roo_scaffold(tmp_path)

        assert len(results) == 6
        for r in results:
            assert "already up to date" in r, f"Expected skip, got: {r}"


class TestInstallRooScaffoldForceOverwrite:
    """Tests force overwrite of different content."""

    def test_install_roo_scaffold_force_overwrite(self, tmp_path):
        """Pre-populate with different content, call with force=True, verify overwritten."""
        roo_dir = get_scaffolds_dir() / "roo"

        # Pre-populate with different content
        for _src_name, dest_relpath in _ROO_SCAFFOLD_FILES.items():
            dest_path = tmp_path / dest_relpath
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text("DIFFERENT CONTENT — should be overwritten\n")

        results = _install_roo_scaffold(tmp_path, force=True)

        assert len(results) == 6
        for r in results:
            assert "overwritten" in r, f"Expected overwritten, got: {r}"

        # Verify content now matches scaffold source
        for src_name, dest_relpath in _ROO_SCAFFOLD_FILES.items():
            src_path = roo_dir / src_name
            dest_path = tmp_path / dest_relpath
            assert dest_path.read_text() == src_path.read_text(), (
                f"Content mismatch after force overwrite: {dest_relpath}"
            )


class TestInstallRooScaffoldSkipPromptsFlag:
    """Tests that --skip-prompts prevents scaffold installation."""

    def test_install_roo_scaffold_skip_prompts_flag(self, tmp_path, monkeypatch):
        """init_strategy(tool='roo', skip_prompts=True) does NOT call _install_roo_scaffold."""
        from engrams import init_command

        scaffold_called = False
        original_install = init_command._install_roo_scaffold

        def mock_install(*args, **kwargs):
            nonlocal scaffold_called
            scaffold_called = True
            return original_install(*args, **kwargs)

        monkeypatch.setattr(init_command, "_install_roo_scaffold", mock_install)

        # Mock _create_and_seed_database to avoid DB creation
        monkeypatch.setattr(
            init_command, "_create_and_seed_database", lambda *a, **kw: None
        )

        # Mock _prompt_team_or_solo to return "team" (avoid interactive prompt)
        monkeypatch.setattr(
            init_command, "_prompt_team_or_solo", lambda: "team"
        )

        # Mock merge_template to return some content (avoid template file deps)
        monkeypatch.setattr(
            init_command, "merge_template", lambda tool: "# mocked strategy content\n"
        )

        exit_code = init_command.init_strategy(
            tool="roo",
            project_dir=str(tmp_path),
            force=True,
            skip_prompts=True,
        )

        assert exit_code == 0, f"init_strategy returned non-zero: {exit_code}"
        assert not scaffold_called, (
            "_install_roo_scaffold was called despite skip_prompts=True"
        )


class TestToolRegistryRooScaffoldFiles:
    """Tests TOOL_REGISTRY structure for roo."""

    def test_tool_registry_roo_scaffold_files(self):
        """TOOL_REGISTRY['roo'] has 'scaffold_files' key with 6 entries."""
        roo_entry = TOOL_REGISTRY["roo"]
        assert "scaffold_files" in roo_entry, (
            "TOOL_REGISTRY['roo'] missing 'scaffold_files' key"
        )
        scaffold_files = roo_entry["scaffold_files"]
        assert isinstance(scaffold_files, list), (
            f"scaffold_files should be a list, got {type(scaffold_files)}"
        )
        assert len(scaffold_files) == 6, (
            f"Expected 6 scaffold_files, got {len(scaffold_files)}: {scaffold_files}"
        )


class TestListToolsOutput:
    """Tests list_tools() stdout output."""

    def test_list_tools_output(self, capsys):
        """Capture stdout from list_tools() and verify it includes scaffold entries."""
        list_tools()
        captured = capsys.readouterr().out

        assert ".roomodes" in captured, (
            "list_tools() output should mention .roomodes"
        )
        assert "system-prompt-flow-" in captured, (
            "list_tools() output should mention system-prompt-flow-"
        )
