"""Tests for token estimation (Feature 3)."""
from engrams.budgeting.estimator import estimate_tokens, _format_entity, estimate_text_tokens


class TestEstimator:
    def test_estimate_compact(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test decision"}
        tokens = estimate_tokens(entity, format="compact")
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_estimate_standard(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test", "rationale": "Because"}
        tokens = estimate_tokens(entity, format="standard")
        assert tokens > 0

    def test_estimate_verbose(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test", "rationale": "Because", "extra": "data"}
        tokens = estimate_tokens(entity, format="verbose")
        assert tokens > 0

    def test_verbose_more_than_compact(self):
        entity = {
            "_type": "decision",
            "id": 1,
            "summary": "Test decision with some detail",
            "rationale": "Because reasons that are longer than the summary",
            "implementation_details": "Here are the details about implementation",
        }
        compact = estimate_tokens(entity, format="compact")
        verbose = estimate_tokens(entity, format="verbose")
        assert verbose >= compact

    def test_format_entity_compact(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test"}
        text = _format_entity(entity, "compact")
        assert "decision" in text.lower() or "Test" in text

    def test_format_entity_standard_includes_rationale(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test", "rationale": "Why"}
        text = _format_entity(entity, "standard")
        assert "rationale" in text.lower()

    def test_format_entity_verbose_includes_all_keys(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test", "custom_field": "value"}
        text = _format_entity(entity, "verbose")
        assert "custom_field" in text

    def test_empty_entity(self):
        tokens = estimate_tokens({}, format="compact")
        assert isinstance(tokens, int)
        assert tokens >= 1  # Minimum of 1

    def test_estimate_text_tokens(self):
        tokens = estimate_text_tokens("This is a test string with some words.")
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_format_entity_compact_with_tags_list(self):
        entity = {"_type": "decision", "id": 1, "summary": "Test", "tags": ["auth", "security"]}
        text = _format_entity(entity, "compact")
        assert "auth" in text
        assert "security" in text

    def test_format_entity_standard_truncates_long_value(self):
        entity = {"_type": "custom_data", "id": 1, "key": "spec", "value": "x" * 1000}
        text = _format_entity(entity, "standard")
        assert "..." in text  # Should be truncated

    def test_format_entity_compact_picks_first_identifier(self):
        """Compact format picks summary/name/description/key in that order."""
        entity_with_name = {"_type": "pattern", "id": 1, "name": "MyPattern"}
        text = _format_entity(entity_with_name, "compact")
        assert "MyPattern" in text

        entity_with_desc = {"_type": "progress", "id": 1, "description": "Do the thing"}
        text = _format_entity(entity_with_desc, "compact")
        assert "Do the thing" in text
