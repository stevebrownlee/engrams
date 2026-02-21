import os
import sys
from pydantic import ValidationError
import pytest

# Ensure 'src' is on sys.path for imports when running tests from repo root
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_PATH = os.path.join(REPO_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from engrams.db.models import (
    GetDecisionsArgs,
    LogProgressArgs,
    GetProgressArgs,
    UpdateProgressArgs,
    DeleteProgressByIdArgs,
    GetSystemPatternsArgs,
    DeleteSystemPatternByIdArgs,
    SearchCustomDataValueArgs,
    SearchProjectGlossaryArgs,
    GetItemHistoryArgs,
    GetRecentActivitySummaryArgs,
    SemanticSearchConportArgs,
)

WS = "dummy_workspace"

def test_get_decisions_limit_accepts_numeric_string():
    m = GetDecisionsArgs(workspace_id=WS, limit=" 10 ")
    assert m.limit == 10

def test_get_decisions_limit_invalid_string_raises():
    with pytest.raises(ValidationError):
        GetDecisionsArgs(workspace_id=WS, limit="ten")

def test_get_decisions_limit_bounds_enforced():
    with pytest.raises(ValidationError):
        GetDecisionsArgs(workspace_id=WS, limit="0")

def test_log_progress_parent_id_coercion():
    m = LogProgressArgs(workspace_id=WS, status="IN_PROGRESS", description="x", parent_id=" 7 ")
    assert m.parent_id == 7

def test_update_progress_id_and_parent_id_coercion_and_bounds():
    m = UpdateProgressArgs(workspace_id=WS, progress_id="5", status="DONE")
    assert m.progress_id == 5
    with pytest.raises(ValidationError):
        UpdateProgressArgs(workspace_id=WS, progress_id="0", status="TODO")
    m2 = UpdateProgressArgs(workspace_id=WS, progress_id=6, parent_id=" 8 ")
    assert m2.parent_id == 8

def test_delete_progress_by_id_bounds():
    with pytest.raises(ValidationError):
        DeleteProgressByIdArgs(workspace_id=WS, progress_id="0")
    m = DeleteProgressByIdArgs(workspace_id=WS, progress_id="3")
    assert m.progress_id == 3

def test_get_progress_filters_and_limit_coercion():
    m = GetProgressArgs(workspace_id=WS, status_filter=None, parent_id_filter=" 2 ", limit="1")
    assert m.parent_id_filter == 2
    assert m.limit == 1

def test_get_system_patterns_limit_coercion():
    m = GetSystemPatternsArgs(workspace_id=WS, limit=" 4 ")
    assert m.limit == 4

def test_delete_system_pattern_by_id_coercion_and_bounds():
    m = DeleteSystemPatternByIdArgs(workspace_id=WS, pattern_id="9")
    assert m.pattern_id == 9
    with pytest.raises(ValidationError):
        DeleteSystemPatternByIdArgs(workspace_id=WS, pattern_id="0")

def test_search_custom_data_value_limit_coercion_and_bounds():
    m = SearchCustomDataValueArgs(workspace_id=WS, query_term="q", limit=" 5 ")
    assert m.limit == 5
    with pytest.raises(ValidationError):
        SearchCustomDataValueArgs(workspace_id=WS, query_term="q", limit="0")

def test_search_project_glossary_limit_coercion():
    m = SearchProjectGlossaryArgs(workspace_id=WS, query_term="gloss", limit="3")
    assert m.limit == 3

def test_get_item_history_version_and_limit_coercion():
    m = GetItemHistoryArgs(workspace_id=WS, item_type="product_context", version=" 2 ", limit="1")
    assert m.version == 2
    assert m.limit == 1
    with pytest.raises(ValidationError):
        GetItemHistoryArgs(workspace_id=WS, item_type="product_context", version="0")

def test_recent_activity_summary_coercion_and_bounds():
    m = GetRecentActivitySummaryArgs(workspace_id=WS, hours_ago="24", limit_per_type=" 3 ")
    assert m.hours_ago == 24
    assert m.limit_per_type == 3
    with pytest.raises(ValidationError):
        GetRecentActivitySummaryArgs(workspace_id=WS, hours_ago="0")

def test_semantic_search_top_k_coercion_and_bounds():
    m = SemanticSearchConportArgs(workspace_id=WS, query_text="what", top_k=" 5 ")
    assert m.top_k == 5
    with pytest.raises(ValidationError):
        SemanticSearchConportArgs(workspace_id=WS, query_text="what", top_k="0")
    with pytest.raises(ValidationError):
        SemanticSearchConportArgs(workspace_id=WS, query_text="what", top_k="26")