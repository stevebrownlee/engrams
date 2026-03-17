"""Tests for governance conflict detection (Feature 1)."""
import pytest
from pydantic import ValidationError

from engrams.db import database as db
from engrams.db import models
from engrams.governance import conflict_detector
from engrams.governance import models as gov_models
from engrams.handlers import mcp_handlers as handlers



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


class TestCheckDecisionConflicts:
    """Test conflict_detector.check_decision_conflicts() — post-write safety net."""

    def test_no_decisions_returns_no_conflicts(self, workspace_id):
        """Test with empty workspace (no decisions in DB)."""
        item_data = {
            "summary": "Some action",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.has_conflict is False
        assert result.conflicts == []

    def test_tag_overlap_detected(self, workspace_id):
        """Test tag overlap detection with existing decision."""
        # Create a decision in DB
        decision = models.Decision(
            summary="Use SQLite as primary database",
            rationale="SQLite is embedded and requires no server setup",
            tags=["database", "architecture"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call with overlapping tags
        item_data = {
            "summary": "Switch to PostgreSQL",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.has_conflict is True
        assert len(result.conflicts) > 0
        assert result.conflicts[0]["type"] == "decision_conflict"

    def test_no_overlap_returns_clean(self, workspace_id):
        """Test no conflict when tags don't overlap."""
        # Create a decision with database tags
        decision = models.Decision(
            summary="Use SQLite as primary database",
            tags=["database"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call with completely different tags
        item_data = {
            "summary": "Use React for frontend",
            "tags": ["frontend", "ui"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.has_conflict is False

    def test_keyword_conflict_detected(self, workspace_id):
        """Test keyword conflict detection (sqlite vs postgresql)."""
        # Create a decision mentioning sqlite
        decision = models.Decision(
            summary="Use sqlite for all persistence",
            tags=["database"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call with postgresql mention and overlapping tags
        item_data = {
            "summary": "Use postgresql for storage",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.has_conflict is True
        assert len(result.conflicts) > 0

    def test_contradiction_keywords_flagged(self, workspace_id):
        """Test contradiction keywords like 'switch' are flagged."""
        # Create a decision
        decision = models.Decision(
            summary="Use SQLite",
            tags=["database"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call with contradiction keyword
        item_data = {
            "summary": "switch database engine",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.has_conflict is True

    def test_action_is_always_warn(self, workspace_id):
        """Test that post-write path always returns action='warn', never 'block'."""
        # Create a conflicting decision
        decision = models.Decision(
            summary="Use SQLite",
            tags=["database"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Trigger a conflict
        item_data = {
            "summary": "Switch to PostgreSQL",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        assert result.action == "warn"

    def test_handles_decision_without_tags(self, workspace_id):
        """Test handling of decisions with no tags."""
        # Create a decision with no tags
        decision = models.Decision(
            summary="Some decision",
            tags=None,
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call with any item_data
        item_data = {
            "summary": "Some action",
            "tags": ["anything"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        # Should not error and should return clean result
        assert result is not None
        assert result.has_conflict is False

    def test_error_returns_empty_result(self, workspace_id, monkeypatch):
        """Test that exceptions are caught and return clean result."""
        # Mock get_decisions to raise an exception
        def mock_get_decisions(*args, **kwargs):
            raise RuntimeError("Database error")

        monkeypatch.setattr(db, "get_decisions", mock_get_decisions)

        item_data = {
            "summary": "Some action",
            "tags": ["database"],
        }
        result = conflict_detector.check_decision_conflicts(
            workspace_id, "decision", item_data
        )
        # Should return clean result without raising
        assert result is not None
        assert result.has_conflict is False


class TestCheckKeywordConflict:
    """Test conflict_detector._check_keyword_conflict() — keyword matching logic."""

    def test_sqlite_postgresql_conflict(self):
        """Test sqlite vs postgresql conflict detection."""
        result = conflict_detector._check_keyword_conflict(
            "use sqlite for storage",
            "use postgresql instead",
            {"database"},
        )
        assert result is True

    def test_no_conflict_same_tech(self):
        """Test no conflict when same technology is mentioned."""
        result = conflict_detector._check_keyword_conflict(
            "use sqlite for storage",
            "sqlite is great",
            {"database"},
        )
        assert result is False

    def test_contradiction_keyword_switch(self):
        """Test contradiction keyword 'switch' is detected."""
        result = conflict_detector._check_keyword_conflict(
            "use sqlite",
            "switch to something else",
            {"database"},
        )
        assert result is True

    def test_no_overlap_tags_returns_false(self):
        """Test no conflict when tags don't overlap."""
        result = conflict_detector._check_keyword_conflict(
            "use sqlite",
            "use postgresql",
            set(),  # Empty tags
        )
        assert result is False

    def test_empty_texts_return_false(self):
        """Test empty texts return False."""
        result = conflict_detector._check_keyword_conflict(
            "",
            "",
            {"database"},
        )
        assert result is False


class TestHandleCheckPlannedAction:
    """Test handlers.handle_check_planned_action() — pre-mutation check handler."""

    def test_no_conflicts_returns_proceed(self, workspace_id):
        """Test handler returns proceed=True when no conflicts."""
        args = gov_models.CheckPlannedActionArgs(
            workspace_id=workspace_id,
            action_description="Add a new feature",
            tags=["feature"],
        )
        result = handlers.handle_check_planned_action(args)
        assert result["blocked"] is False
        assert result["proceed"] is True

    def test_conflict_returns_blocked(self, workspace_id):
        """Test handler returns blocked=True when conflicts exist."""
        # Create a conflicting decision
        decision = models.Decision(
            summary="Use SQLite as primary database",
            tags=["database"],
            visibility="individual",
        )
        db.log_decision(workspace_id, decision)

        # Call handler with conflicting action
        args = gov_models.CheckPlannedActionArgs(
            workspace_id=workspace_id,
            action_description="Switch to PostgreSQL database",
            tags=["database"],
        )
        result = handlers.handle_check_planned_action(args)
        assert result["blocked"] is True
        assert result["proceed"] is False
        assert len(result["conflicts"]) > 0

    def test_handler_returns_decision_details(self, workspace_id):
        """Test handler returns decision details in conflicts."""
        # Create a conflicting decision
        decision = models.Decision(
            summary="Use SQLite as primary database",
            tags=["database"],
            visibility="individual",
        )
        logged = db.log_decision(workspace_id, decision)

        # Call handler
        args = gov_models.CheckPlannedActionArgs(
            workspace_id=workspace_id,
            action_description="Switch to PostgreSQL",
            tags=["database"],
        )
        result = handlers.handle_check_planned_action(args)

        # Verify conflict entries contain decision details
        assert len(result["conflicts"]) > 0
        conflict = result["conflicts"][0]
        assert "decision_id" in conflict
        assert "decision_summary" in conflict
        assert "decision_uuid" in conflict

    def test_handler_error_returns_permissive(self, workspace_id, monkeypatch):
        """Test handler returns permissive result on error."""
        # Mock check_decision_conflicts to raise an exception
        def mock_check(*args, **kwargs):
            raise RuntimeError("Check failed")

        monkeypatch.setattr(
            conflict_detector, "check_decision_conflicts", mock_check
        )

        args = gov_models.CheckPlannedActionArgs(
            workspace_id=workspace_id,
            action_description="Some action",
            tags=["database"],
        )
        result = handlers.handle_check_planned_action(args)

        # Should return permissive result
        assert result["blocked"] is False
        assert result["proceed"] is True


class TestCheckPlannedActionArgs:
    """Test gov_models.CheckPlannedActionArgs validation."""

    def test_valid_args(self):
        """Test valid args creation."""
        args = gov_models.CheckPlannedActionArgs(
            workspace_id="/tmp/test",
            action_description="Do something",
        )
        assert args.workspace_id == "/tmp/test"
        assert args.action_description == "Do something"

    def test_empty_action_description_fails(self):
        """Test empty action_description raises ValidationError."""
        with pytest.raises(ValidationError):
            gov_models.CheckPlannedActionArgs(
                workspace_id="/tmp/test",
                action_description="",
            )

    def test_tags_optional(self):
        """Test tags parameter is optional."""
        args = gov_models.CheckPlannedActionArgs(
            workspace_id="/tmp/test",
            action_description="Do something",
        )
        assert args.tags is None
