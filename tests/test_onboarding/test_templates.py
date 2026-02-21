"""Tests for onboarding templates (Feature 4)."""
from engrams.onboarding.templates import (
    get_sections_for_level, get_default_budget,
    BRIEFING_SECTIONS, BRIEFING_LEVELS, LEVEL_DEPTH,
)


class TestTemplates:
    def test_executive_level_has_fewest_sections(self):
        exec_sections = get_sections_for_level("executive")
        overview_sections = get_sections_for_level("overview")
        assert len(exec_sections) <= len(overview_sections)

    def test_overview_more_than_executive(self):
        exec_sections = get_sections_for_level("executive")
        overview_sections = get_sections_for_level("overview")
        assert len(overview_sections) > len(exec_sections)

    def test_detailed_more_than_overview(self):
        overview_sections = get_sections_for_level("overview")
        detailed_sections = get_sections_for_level("detailed")
        assert len(detailed_sections) > len(overview_sections)

    def test_comprehensive_has_all_sections(self):
        comp_sections = get_sections_for_level("comprehensive")
        assert len(comp_sections) == len(BRIEFING_SECTIONS)

    def test_section_filter(self):
        sections = get_sections_for_level("comprehensive", section_filter=["project_identity", "glossary"])
        assert len(sections) == 2
        ids = [s["id"] for s in sections]
        assert "project_identity" in ids
        assert "glossary" in ids

    def test_section_filter_nonexistent(self):
        sections = get_sections_for_level("comprehensive", section_filter=["nonexistent_section"])
        assert len(sections) == 0

    def test_default_budgets(self):
        assert get_default_budget("executive") == 500
        assert get_default_budget("overview") == 2000
        assert get_default_budget("detailed") == 5000
        assert get_default_budget("comprehensive") == 20000

    def test_default_budget_unknown_level(self):
        assert get_default_budget("unknown_level") == 2000  # fallback

    def test_level_depth_ordering(self):
        assert LEVEL_DEPTH["executive"] < LEVEL_DEPTH["overview"]
        assert LEVEL_DEPTH["overview"] < LEVEL_DEPTH["detailed"]
        assert LEVEL_DEPTH["detailed"] < LEVEL_DEPTH["comprehensive"]

    def test_briefing_levels_list(self):
        assert BRIEFING_LEVELS == ["executive", "overview", "detailed", "comprehensive"]

    def test_all_sections_have_required_keys(self):
        for section in BRIEFING_SECTIONS:
            assert "id" in section
            assert "title" in section
            assert "min_level" in section
            assert "source" in section
            assert "description" in section

    def test_executive_sections_only_executive_min_level(self):
        """Executive sections should only include those with min_level='executive'."""
        exec_sections = get_sections_for_level("executive")
        for s in exec_sections:
            assert s["min_level"] == "executive"

    def test_section_ids_unique(self):
        ids = [s["id"] for s in BRIEFING_SECTIONS]
        assert len(ids) == len(set(ids))

    def test_known_section_ids(self):
        """Verify the expected section IDs exist."""
        ids = {s["id"] for s in BRIEFING_SECTIONS}
        expected = {
            "project_identity", "current_status", "architecture",
            "key_decisions", "active_tasks", "risks_and_concerns",
            "all_decisions", "patterns", "glossary", "knowledge_graph",
        }
        for eid in expected:
            assert eid in ids, f"Expected section '{eid}' not found"
