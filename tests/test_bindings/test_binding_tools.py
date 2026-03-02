"""Tests for code binding MCP tools (Feature 2)."""
import json
import pytest

from engrams.db import models
from engrams.bindings import models as binding_models
from engrams.handlers import mcp_handlers as H


def as_dict(obj):
    if isinstance(obj, dict):
        return obj
    try:
        return obj.model_dump(mode="json")
    except Exception:
        return json.loads(json.dumps(obj, default=str))



@pytest.fixture
def sample_decision(workspace_id):
    """Create a decision to bind to."""
    dec = H.handle_log_decision(models.LogDecisionArgs(
        workspace_id=workspace_id,
        summary="Binding test decision",
        rationale="For binding test",
    ))
    return as_dict(dec)


class TestBindingCRUD:
    def test_bind_code_to_item(self, workspace_id, sample_decision):
        result = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/auth/**/*.py",
            binding_type="implements",
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_bind_code_with_symbol_pattern(self, workspace_id, sample_decision):
        result = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/auth/**/*.py",
            symbol_pattern="AuthMiddleware",
            binding_type="implements",
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_bind_code_with_confidence(self, workspace_id, sample_decision):
        result = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/db/**/*.py",
            binding_type="governed_by",
            confidence="agent_suggested",
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_get_bindings_for_item(self, workspace_id, sample_decision):
        # Create a binding first
        H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/db/**/*.py",
            binding_type="governed_by",
        ))

        result = H.handle_get_bindings_for_item(binding_models.GetBindingsForItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
        ))
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_get_context_for_files(self, workspace_id, sample_decision):
        # Create a binding
        H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/engrams/main.py",
            binding_type="implements",
        ))

        result = H.handle_get_context_for_files(binding_models.GetContextForFilesArgs(
            workspace_id=workspace_id,
            file_paths=["src/engrams/main.py"],
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_get_stale_bindings(self, workspace_id):
        result = H.handle_get_stale_bindings(binding_models.GetStaleBindingsArgs(
            workspace_id=workspace_id,
            days_stale=30,
        ))
        assert isinstance(result, list)

    def test_suggest_bindings(self, workspace_id, sample_decision):
        result = H.handle_suggest_bindings(binding_models.SuggestBindingsArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
        ))
        d = as_dict(result)
        assert d["status"] == "success"

    def test_unbind_code_from_item(self, workspace_id, sample_decision):
        # Create a binding first
        bind_result = H.handle_bind_code_to_item(binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type="decision",
            item_id=sample_decision["id"],
            file_pattern="src/temp/**/*.py",
            binding_type="tests",
        ))
        binding_id = as_dict(bind_result).get("binding_id") or as_dict(bind_result).get("id")

        if binding_id:
            result = H.handle_unbind_code_from_item(binding_models.UnbindCodeFromItemArgs(
                workspace_id=workspace_id,
                binding_id=binding_id,
            ))
            d = as_dict(result)
            assert d["status"] == "success"


class TestBindingValidation:
    def test_invalid_binding_type_rejected(self, workspace_id):
        with pytest.raises(Exception):
            binding_models.BindCodeToItemArgs(
                workspace_id=workspace_id,
                item_type="decision",
                item_id=1,
                file_pattern="src/**/*.py",
                binding_type="invalid_type",
            )

    def test_empty_file_pattern_rejected(self, workspace_id):
        with pytest.raises(Exception):
            binding_models.BindCodeToItemArgs(
                workspace_id=workspace_id,
                item_type="decision",
                item_id=1,
                file_pattern="",
                binding_type="implements",
            )
