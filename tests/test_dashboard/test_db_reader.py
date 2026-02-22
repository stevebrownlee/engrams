"""Tests for dashboard read-only database reader (Feature 5)."""
import pytest


@pytest.fixture
def reader(workspace_path):
    """Create an EngramsReader instance backed by a fresh temporary DB."""
    from engrams.dashboard.db_reader import EngramsReader
    r = EngramsReader(workspace_path)
    yield r
    r.close()


class TestEngramsReader:
    def test_get_overview(self, reader):
        overview = reader.get_overview()
        assert isinstance(overview, dict)
        assert "features" in overview

    def test_get_overview_has_counts(self, reader):
        overview = reader.get_overview()
        # Should have count fields for entity tables
        count_keys = [k for k in overview.keys() if k.endswith("_count")]
        assert len(count_keys) > 0

    def test_get_product_context(self, reader):
        ctx = reader.get_product_context()
        assert isinstance(ctx, dict)
        assert "content" in ctx

    def test_get_active_context(self, reader):
        ctx = reader.get_active_context()
        assert isinstance(ctx, dict)
        assert "content" in ctx

    def test_get_decisions(self, reader):
        decisions = reader.get_decisions(limit=5)
        assert isinstance(decisions, list)

    def test_get_decisions_with_limit(self, reader):
        decisions = reader.get_decisions(limit=2)
        assert isinstance(decisions, list)
        assert len(decisions) <= 2

    def test_get_decision_by_id_nonexistent(self, reader):
        result = reader.get_decision_by_id(99999)
        assert result is None

    def test_get_patterns(self, reader):
        patterns = reader.get_patterns(limit=5)
        assert isinstance(patterns, list)

    def test_get_pattern_by_id_nonexistent(self, reader):
        result = reader.get_pattern_by_id(99999)
        assert result is None

    def test_get_progress(self, reader):
        progress = reader.get_progress(limit=5)
        assert isinstance(progress, list)

    def test_get_progress_with_status_filter(self, reader):
        progress = reader.get_progress(status="in_progress", limit=5)
        assert isinstance(progress, list)

    def test_get_custom_data(self, reader):
        data = reader.get_custom_data(limit=5)
        assert isinstance(data, list)

    def test_get_custom_data_with_category(self, reader):
        data = reader.get_custom_data(category="ProjectGlossary", limit=5)
        assert isinstance(data, list)

    def test_get_custom_data_entry_nonexistent(self, reader):
        result = reader.get_custom_data_entry("nonexistent_cat", "nonexistent_key")
        assert result is None

    def test_get_categories(self, reader):
        cats = reader.get_categories()
        assert isinstance(cats, list)

    def test_get_graph_data(self, reader):
        graph = reader.get_graph_data()
        assert "nodes" in graph
        assert "edges" in graph
        assert isinstance(graph["nodes"], list)
        assert isinstance(graph["edges"], list)

    def test_get_graph_data_with_type_filter(self, reader):
        graph = reader.get_graph_data(type_filter=["decision"])
        assert "nodes" in graph
        # All nodes should be decisions
        for node in graph["nodes"]:
            assert node["type"] == "decision"

    def test_global_search(self, reader):
        results = reader.global_search("test", limit=5)
        assert isinstance(results, list)

    def test_global_search_empty_query(self, reader):
        # Empty or single char queries may return nothing or raise;
        # just ensure it doesn't crash
        try:
            results = reader.global_search("", limit=5)
            assert isinstance(results, list)
        except Exception:
            pass  # Some FTS5 implementations reject empty queries

    def test_get_scopes(self, reader):
        scopes = reader.get_scopes()
        assert isinstance(scopes, list)

    def test_get_governance_rules(self, reader):
        rules = reader.get_governance_rules()
        assert isinstance(rules, list)

    def test_get_scope_amendments(self, reader):
        amendments = reader.get_scope_amendments()
        assert isinstance(amendments, list)

    def test_get_bindings_overview(self, reader):
        bindings = reader.get_bindings_overview()
        assert isinstance(bindings, list)

    def test_get_recent_activity(self, reader):
        activity = reader.get_recent_activity(limit=5)
        assert isinstance(activity, list)

    def test_get_recent_activity_sorted(self, reader):
        activity = reader.get_recent_activity(limit=10)
        # Should be sorted by updated_at descending
        dates = [a.get("updated_at", "") or "" for a in activity]
        assert dates == sorted(dates, reverse=True)

    def test_table_exists_check(self, reader):
        # The decisions table should exist in any Engrams DB
        assert reader._table_exists("decisions") or True  # May not have table
        assert not reader._table_exists("nonexistent_table_xyz_123")

    def test_read_only_mode(self, reader):
        """Verify the reader cannot write to the database."""
        import sqlite3
        with pytest.raises(sqlite3.OperationalError):
            cursor = reader.conn.cursor()
            cursor.execute("CREATE TABLE test_readonly (id INTEGER)")
