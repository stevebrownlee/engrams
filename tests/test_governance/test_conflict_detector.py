"""Tests for governance conflict detection (Feature 1)."""
import pytest

from engrams.governance import conflict_detector
from engrams.governance import models as gov_models



class TestConflictDetection:
    def test_check_conflicts_no_conflicts(self, workspace_id):
        """Test that items with no conflicting team rules pass."""
        item_data = {
            "summary": "A simple decision",
            "tags": ["safe", "approved"],
        }
        result = conflict_detector.check_conflicts(
            workspace_id, "decision", item_data, scope_id=None
        )
        # With no scope, should return empty/no conflicts
        assert result is not None
        assert result.has_conflict is False
        assert result.action == "allow"

    def test_check_conflicts_returns_result_model(self, workspace_id):
        """Test that check_conflicts returns a ConflictCheckResult."""
        item_data = {"summary": "Test"}
        result = conflict_detector.check_conflicts(
            workspace_id, "decision", item_data, scope_id=None
        )
        assert isinstance(result, gov_models.ConflictCheckResult)

    def test_rule_match_blocked_tags(self):
        """Test _does_rule_match with blocked_tags rule."""
        rule = gov_models.GovernanceRule(
            scope_id=1,
            rule_type="hard_block",
            entity_type="decision",
            rule_definition={"blocked_tags": ["forbidden"]},
            description="Block forbidden tag",
        )
        item_with_tag = {"tags": ["forbidden", "other"]}
        result = conflict_detector._does_rule_match(rule, item_with_tag)
        assert result is not None  # Should match
        assert "blocked_tags_found" in result

    def test_rule_match_no_match(self):
        """Test _does_rule_match with non-matching item."""
        rule = gov_models.GovernanceRule(
            scope_id=1,
            rule_type="hard_block",
            entity_type="decision",
            rule_definition={"blocked_tags": ["forbidden"]},
            description="Block forbidden tag",
        )
        item_without_tag = {"tags": ["safe", "approved"]}
        result = conflict_detector._does_rule_match(rule, item_without_tag)
        assert result is None  # Should not match

    def test_rule_match_required_tags_missing(self):
        """Test _does_rule_match with required_tags that are absent."""
        rule = gov_models.GovernanceRule(
            scope_id=1,
            rule_type="soft_warn",
            entity_type="decision",
            rule_definition={"required_tags": ["reviewed", "approved"]},
            description="Require reviewed and approved tags",
        )
        item_data = {"tags": ["reviewed"]}  # missing "approved"
        result = conflict_detector._does_rule_match(rule, item_data)
        assert result is not None
        assert "required_tags_missing" in result
        assert "approved" in result["required_tags_missing"]

    def test_rule_match_blocked_keywords(self):
        """Test _does_rule_match with blocked_keywords rule."""
        rule = gov_models.GovernanceRule(
            scope_id=1,
            rule_type="hard_block",
            entity_type="decision",
            rule_definition={"blocked_keywords": ["mongo"]},
            description="Block MongoDB references",
        )
        item_data = {"summary": "Use MongoDB for storage"}
        result = conflict_detector._does_rule_match(rule, item_data)
        assert result is not None
        assert "blocked_keywords_found" in result

    def test_rule_match_empty_rule_definition(self):
        """Test _does_rule_match with empty rule definition."""
        rule = gov_models.GovernanceRule(
            scope_id=1,
            rule_type="hard_block",
            entity_type="decision",
            rule_definition={},
            description="Empty rule",
        )
        item_data = {"tags": ["anything"], "summary": "Test"}
        result = conflict_detector._does_rule_match(rule, item_data)
        assert result is None  # Empty rule should not match

    def test_conflict_check_result_defaults(self):
        """Test ConflictCheckResult default values."""
        result = gov_models.ConflictCheckResult()
        assert result.has_conflict is False
        assert result.action == "allow"
        assert result.conflicts == []
        assert result.warnings == []
        assert result.amendments_created == []
