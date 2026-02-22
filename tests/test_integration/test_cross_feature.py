"""Cross-feature integration tests."""
import json
import pytest

from engrams.db import models
from engrams.governance import models as gov_models
from engrams.bindings import models as binding_models
from engrams.handlers import mcp_handlers as H


def as_dict(obj):
    if isinstance(obj, dict):
        return obj
    try:
        return obj.model_dump(mode="json")
    except Exception:
        return json.loads(json.dumps(obj, default=str))



class TestGovernanceWithLogTools:
    """Test that existing log tools work with scope_id/visibility params."""

    def test_log_decision_with_scope(self, workspace_id):
        # Create a scope
        scope = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Cross Feature Team",
            created_by="test",
        ))
        scope_id = as_dict(scope)["scope"]["id"]

        # Log decision with scope
        result = H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Scoped decision",
            rationale="Testing governance integration",
            scope_id=scope_id,
            visibility="team",
        ))
        d = as_dict(result)
        assert "id" in d

    def test_log_decision_without_scope_still_works(self, workspace_id):
        """Backward compatibility: no scope params should work fine."""
        result = H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Unscoped decision",
            rationale="No governance params",
        ))
        d = as_dict(result)
        assert "id" in d

    def test_log_decision_with_invalid_visibility_rejected(self, workspace_id):
        """Invalid visibility should be rejected by model validation."""
        with pytest.raises(Exception):
            models.LogDecisionArgs(
                workspace_id=workspace_id,
                summary="Bad visibility",
                rationale="Testing",
                visibility="invalid_visibility",
            )


class TestBindingsWithDecisions:
    """Test binding code to decisions and retrieving context."""

    def test_full_binding_workflow(self, workspace_id):
        # 1. Create decision
        dec = H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Full binding workflow decision",
            rationale="Testing end-to-end",
        ))
        dec_id = as_dict(dec)["id"]

        # 2. Bind code to it
        bind = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=dec_id,
            file_pattern="src/context_portal_mcp/**/*.py",
            binding_type="implements",
        ))
        assert as_dict(bind)["status"] == "success"

        # 3. Retrieve context for a file
        ctx = H.handle_get_context_for_files(binding_models.GetContextForFilesArgs(
            workspace_id=workspace_id,
            file_paths=["src/context_portal_mcp/main.py"],
        ))
        ctx_d = as_dict(ctx)
        assert ctx_d["status"] == "success"
        assert ctx_d["total_entities"] >= 1

    def test_binding_and_verify(self, workspace_id):
        """Create a binding and verify it."""
        # Create decision
        dec = H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Verify binding decision",
            rationale="Testing verification",
        ))
        dec_id = as_dict(dec)["id"]

        # Bind
        H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=dec_id,
            file_pattern="src/**/*.py",
            binding_type="governed_by",
        ))

        # Verify
        verify_result = H.handle_verify_bindings(binding_models.VerifyBindingsArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=dec_id,
        ))
        d = as_dict(verify_result)
        assert d["status"] == "success"


class TestBudgetingIntegration:
    """Test budgeting tools retrieve real data."""

    def test_estimate_context_size(self, workspace_id):
        from engrams.budgeting import models as budget_models
        result = H.handle_estimate_context_size(budget_models.EstimateContextSizeArgs(
            workspace_id=workspace_id,
            task_description="Test task",
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert "total_entities" in d

    def test_get_budget_config(self, workspace_id):
        from engrams.budgeting import models as budget_models
        result = H.handle_get_context_budget_config(budget_models.GetContextBudgetConfigArgs(
            workspace_id=workspace_id,
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert "weights" in d

    def test_get_relevant_context(self, workspace_id):
        from engrams.budgeting import models as budget_models
        # First create some data to retrieve
        H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Budget test decision about authentication",
            rationale="For testing relevant context retrieval",
        ))

        result = H.handle_get_relevant_context(budget_models.GetRelevantContextArgs(
            workspace_id=workspace_id,
            task_description="authentication",
            token_budget=5000,
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert "selected" in d

    def test_update_budget_config(self, workspace_id):
        from engrams.budgeting import models as budget_models
        result = H.handle_update_context_budget_config(budget_models.UpdateContextBudgetConfigArgs(
            workspace_id=workspace_id,
            weights={"recency": 0.5, "semantic_similarity": 0.2},
        ))
        d = as_dict(result)
        assert d["status"] == "success"


class TestOnboardingIntegration:
    """Test onboarding briefings with real data."""

    def test_executive_briefing(self, workspace_id):
        from engrams.onboarding import models as onb_models
        result = H.handle_get_project_briefing(onb_models.GetProjectBriefingArgs(
            workspace_id=workspace_id,
            level="executive",
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert "sections" in d

    def test_overview_briefing(self, workspace_id):
        from engrams.onboarding import models as onb_models
        result = H.handle_get_project_briefing(onb_models.GetProjectBriefingArgs(
            workspace_id=workspace_id,
            level="overview",
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert len(d["sections"]) > 0

    def test_briefing_staleness(self, workspace_id):
        from engrams.onboarding import models as onb_models
        result = H.handle_get_briefing_staleness(onb_models.GetBriefingStalenessArgs(
            workspace_id=workspace_id,
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert "sections" in d

    def test_section_detail(self, workspace_id):
        from engrams.onboarding import models as onb_models
        result = H.handle_get_section_detail(onb_models.GetSectionDetailArgs(
            workspace_id=workspace_id,
            section_id="project_identity",
        ))
        d = as_dict(result)
        assert d["status"] == "success"


class TestGovernanceAndBindingsCombined:
    """Test governance scoping with code bindings."""

    def test_scoped_decision_with_binding(self, workspace_id):
        # Create team scope
        scope = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Combined Test Team",
            created_by="test",
        ))
        scope_id = as_dict(scope)["scope"]["id"]

        # Log scoped decision
        dec = H.handle_log_decision(models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Scoped decision with binding",
            rationale="Testing combined features",
            scope_id=scope_id,
            visibility="team",
        ))
        dec_id = as_dict(dec)["id"]

        # Bind code to it
        bind = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=dec_id,
            file_pattern="src/context_portal_mcp/governance/**/*.py",
            binding_type="implements",
        ))
        assert as_dict(bind)["status"] == "success"

        # Retrieve context for governance files
        ctx = H.handle_get_context_for_files(binding_models.GetContextForFilesArgs(
            workspace_id=workspace_id,
            file_paths=["src/context_portal_mcp/governance/models.py"],
        ))
        ctx_d = as_dict(ctx)
        assert ctx_d["status"] == "success"
        assert ctx_d["total_entities"] >= 1
