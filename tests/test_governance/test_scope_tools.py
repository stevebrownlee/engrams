"""Tests for governance scope tools (Feature 1)."""
import os
import json
import pytest

from engrams.governance import models as gov_models
from engrams.handlers import mcp_handlers as H


def as_dict(obj):
    if isinstance(obj, dict):
        return obj
    try:
        return obj.model_dump(mode="json")
    except Exception:
        return json.loads(json.dumps(obj, default=str))


@pytest.fixture
def workspace_id():
    return os.getcwd()


class TestScopeOperations:
    def test_create_team_scope(self, workspace_id):
        result = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Test Team",
            created_by="test_user",
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert d["scope"]["scope_type"] == "team"
        assert d["scope"]["scope_name"] == "Test Team"

    def test_create_individual_scope(self, workspace_id):
        # First create a team scope to be parent
        team = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Parent Team",
            created_by="test_user",
        ))
        team_id = as_dict(team)["scope"]["id"]

        result = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="individual",
            scope_name="Dev User",
            created_by="dev_user",
            parent_scope_id=team_id,
        ))
        d = as_dict(result)
        assert d["status"] == "success"
        assert d["scope"]["scope_type"] == "individual"
        assert d["scope"]["parent_scope_id"] == team_id

    def test_get_scopes(self, workspace_id):
        result = H.handle_get_scopes(gov_models.GetScopesArgs(
            workspace_id=workspace_id,
        ))
        assert isinstance(result, list)

    def test_get_scopes_filtered(self, workspace_id):
        result = H.handle_get_scopes(gov_models.GetScopesArgs(
            workspace_id=workspace_id,
            scope_type="team",
        ))
        assert isinstance(result, list)
        for s in result:
            d = as_dict(s)
            assert d["scope_type"] == "team"

    def test_invalid_scope_type_rejected(self, workspace_id):
        with pytest.raises(Exception):
            gov_models.CreateScopeArgs(
                workspace_id=workspace_id,
                scope_type="invalid",
                scope_name="Bad Scope",
                created_by="test",
            )


class TestGovernanceRules:
    def test_log_governance_rule(self, workspace_id):
        # Create a scope first
        scope = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Rule Test Team",
            created_by="test_user",
        ))
        scope_id = as_dict(scope)["scope"]["id"]

        result = H.handle_log_governance_rule(gov_models.LogGovernanceRuleArgs(
            workspace_id=workspace_id,
            scope_id=scope_id,
            rule_type="hard_block",
            entity_type="decision",
            rule_definition={"blocked_tags": ["deprecated"]},
            description="Block deprecated decisions",
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_get_governance_rules(self, workspace_id):
        # Create scope + rule
        scope = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Get Rules Team",
            created_by="test_user",
        ))
        scope_id = as_dict(scope)["scope"]["id"]

        result = H.handle_get_governance_rules(gov_models.GetGovernanceRulesArgs(
            workspace_id=workspace_id,
            scope_id=scope_id,
        ))
        assert isinstance(result, list)


class TestAmendments:
    def test_get_scope_amendments(self, workspace_id):
        result = H.handle_get_scope_amendments(gov_models.GetScopeAmendmentsArgs(
            workspace_id=workspace_id,
        ))
        assert isinstance(result, list)


class TestEffectiveContext:
    def test_get_effective_context(self, workspace_id):
        # Create team + individual scope
        team = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="team",
            scope_name="Effective Context Team",
            created_by="test_user",
        ))
        team_id = as_dict(team)["scope"]["id"]

        indiv = H.handle_create_scope(gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type="individual",
            scope_name="Effective Context Dev",
            created_by="dev_user",
            parent_scope_id=team_id,
        ))
        indiv_id = as_dict(indiv)["scope"]["id"]

        result = H.handle_get_effective_context(gov_models.GetEffectiveContextArgs(
            workspace_id=workspace_id,
            scope_id=indiv_id,
        ))
        d = as_dict(result)
        assert d.get("status") == "success" or "decisions" in d
