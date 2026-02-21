"""Tests for briefing generation (Feature 4)."""
import os
import pytest

from engrams.onboarding import briefing


@pytest.fixture
def workspace_id():
    return os.getcwd()


class TestBriefing:
    def test_generate_executive_briefing(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="executive")
        assert result["level"] == "executive"
        assert "sections" in result
        assert "data_coverage" in result
        assert "generated_at" in result
        assert "token_budget" in result

    def test_generate_overview_briefing(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="overview")
        assert result["level"] == "overview"
        exec_result = briefing.generate_briefing(workspace_id, level="executive")
        assert len(result["sections"]) >= len(exec_result["sections"])

    def test_generate_detailed_briefing(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="detailed")
        assert result["level"] == "detailed"
        overview_result = briefing.generate_briefing(workspace_id, level="overview")
        assert len(result["sections"]) >= len(overview_result["sections"])

    def test_check_staleness(self, workspace_id):
        result = briefing.check_briefing_staleness(workspace_id)
        assert "sections" in result
        assert "stale_count" in result
        assert isinstance(result["stale_count"], int)
        assert "stale_threshold_days" in result

    def test_get_section_detail(self, workspace_id):
        result = briefing.get_section_detail(workspace_id, "project_identity")
        assert result.get("status") == "success" or "content" in result

    def test_get_section_detail_unknown(self, workspace_id):
        result = briefing.get_section_detail(workspace_id, "nonexistent_section")
        assert result["status"] == "error"

    def test_briefing_with_token_budget(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="overview", token_budget=1000)
        assert result["token_budget"] == 1000

    def test_briefing_default_budget_per_level(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="executive")
        assert result["token_budget"] == 500  # Default for executive

    def test_briefing_sections_have_expected_keys(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="executive")
        for section in result["sections"]:
            assert "id" in section
            assert "title" in section
            assert "content" in section
            assert "staleness_days" in section
            assert "entity_count" in section

    def test_data_coverage_structure(self, workspace_id):
        result = briefing.generate_briefing(workspace_id, level="executive")
        cov = result["data_coverage"]
        assert "total_decisions" in cov
        assert "included_decisions" in cov
        assert "total_patterns" in cov
        assert "included_patterns" in cov

    def test_briefing_with_section_filter(self, workspace_id):
        result = briefing.generate_briefing(
            workspace_id, level="comprehensive", sections=["project_identity"]
        )
        ids = [s["id"] for s in result["sections"]]
        assert "project_identity" in ids

    def test_staleness_sections_have_section_id(self, workspace_id):
        result = briefing.check_briefing_staleness(workspace_id)
        for section in result["sections"]:
            assert "section_id" in section
            assert "title" in section
            assert "status" in section


class TestBriefingHelpers:
    def test_compute_staleness_days_none(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = briefing._compute_staleness_days(now, None)
        assert result is None

    def test_compute_staleness_days_string(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=5)).isoformat()
        result = briefing._compute_staleness_days(now, past)
        assert result is not None
        assert 4 <= result <= 6  # Allow slight variance

    def test_compute_staleness_days_datetime(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=10)
        result = briefing._compute_staleness_days(now, past)
        assert result == 10
