"""Tests for code binding matcher (Feature 2)."""
import os

from engrams.bindings import matcher


class TestGlobMatching:
    def test_match_simple_pattern(self):
        assert matcher.match_file_against_pattern("src/auth/login.py", "src/auth/*.py")

    def test_match_recursive_pattern(self):
        assert matcher.match_file_against_pattern("src/auth/middleware/jwt.py", "src/auth/**/*.py")

    def test_no_match(self):
        assert not matcher.match_file_against_pattern("src/db/models.py", "src/auth/*.py")

    def test_exact_file_match(self):
        assert matcher.match_file_against_pattern("src/main.py", "src/main.py")

    def test_match_with_extension(self):
        assert matcher.match_file_against_pattern("tests/test_auth.py", "tests/test_*.py")
        assert not matcher.match_file_against_pattern("tests/test_auth.js", "tests/test_*.py")

    def test_no_match_different_directory(self):
        assert not matcher.match_file_against_pattern("lib/auth/login.py", "src/auth/*.py")

    def test_match_deeply_nested(self):
        assert matcher.match_file_against_pattern(
            "src/auth/providers/oauth/google.py",
            "src/auth/**/*.py",
        )


class TestSymbolCheck:
    def test_check_symbol_in_python_file(self):
        """Test checking for a symbol in an actual Python file."""
        # Use this test file itself as the file to check
        this_file = __file__
        assert matcher.check_symbol_in_file(this_file, "TestSymbolCheck")
        assert not matcher.check_symbol_in_file(this_file, "NonExistentClass12345")

    def test_check_symbol_nonexistent_file(self):
        assert not matcher.check_symbol_in_file("/nonexistent/file.py", "SomeSymbol")

    def test_check_symbol_case_sensitive(self):
        """Symbol search should be case-sensitive."""
        this_file = __file__
        assert matcher.check_symbol_in_file(this_file, "TestSymbolCheck")
        assert not matcher.check_symbol_in_file(this_file, "testsymbolcheck")


class TestMatchFilesInWorkspace:
    def test_match_existing_pattern(self):
        """Test expanding a glob pattern against the actual workspace."""
        workspace = os.getcwd()
        matched = matcher.match_files_in_workspace(workspace, "src/**/*.py")
        assert isinstance(matched, list)
        assert len(matched) > 0  # Should find Python files in src/

    def test_match_nonexistent_pattern(self):
        workspace = os.getcwd()
        matched = matcher.match_files_in_workspace(workspace, "nonexistent_dir/**/*.xyz")
        assert matched == []

    def test_match_invalid_workspace(self):
        matched = matcher.match_files_in_workspace("/nonexistent/path", "*.py")
        assert matched == []


class TestVerifyBindingPattern:
    def test_verify_existing_pattern(self):
        """Test verifying a pattern that matches files in the workspace."""
        workspace = os.getcwd()
        status, files_count, notes = matcher.verify_binding_pattern(workspace, "src/**/*.py")
        assert status == "valid"
        assert files_count > 0
        assert notes is not None

    def test_verify_empty_pattern(self):
        """Test verifying a pattern that matches no files."""
        workspace = os.getcwd()
        status, files_count, notes = matcher.verify_binding_pattern(
            workspace, "nonexistent_dir/**/*.xyz"
        )
        assert status == "pattern_empty"
        assert files_count == 0

    def test_verify_with_symbol_pattern(self):
        """Test verifying with a symbol pattern."""
        workspace = os.getcwd()
        status, files_count, notes = matcher.verify_binding_pattern(
            workspace, "src/**/*.py", symbol_pattern="def "
        )
        # Should find 'def ' in Python source files
        assert status == "valid"
        assert files_count > 0

    def test_verify_with_missing_symbol(self):
        """Test verifying with a symbol pattern that doesn't exist."""
        workspace = os.getcwd()
        status, files_count, notes = matcher.verify_binding_pattern(
            workspace, "src/**/*.py", symbol_pattern="XYZNONEXISTENT123456"
        )
        assert status == "symbol_not_found"
        assert files_count > 0  # Files matched but symbol not found
