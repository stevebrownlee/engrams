"""Tests for budgeting scorer (Feature 3)."""
from datetime import datetime, timezone

from engrams.budgeting.scorer import score_entities, ScoredEntity, LIFECYCLE_SCORES


class TestScorer:
    def test_score_entities_basic(self):
        entities = [
            {"_type": "decision", "id": 1, "summary": "Test", "updated_at": datetime.now(timezone.utc).isoformat()},
            {"_type": "system_pattern", "id": 2, "name": "Pattern", "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        result = score_entities(entities)
        assert len(result) == 2
        assert all(isinstance(r, ScoredEntity) for r in result)
        assert all(0 <= r.total_score <= 1 for r in result)

    def test_score_entities_sorted_descending(self):
        entities = [
            {"_type": "decision", "id": 1, "status": "deprecated", "updated_at": "2020-01-01T00:00:00Z"},
            {"_type": "decision", "id": 2, "status": "accepted", "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        result = score_entities(entities)
        assert result[0].total_score >= result[1].total_score

    def test_score_with_link_counts(self):
        entities = [
            {"_type": "decision", "id": 1, "updated_at": datetime.now(timezone.utc).isoformat()},
            {"_type": "decision", "id": 2, "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        link_counts = {"decision:1": 10, "decision:2": 0}
        result = score_entities(entities, link_counts=link_counts)
        # Entity with more links should score higher on reference_frequency
        entity_1 = next(r for r in result if r.entity_id == 1)
        entity_2 = next(r for r in result if r.entity_id == 2)
        assert entity_1.score_breakdown["reference_frequency"] > entity_2.score_breakdown["reference_frequency"]

    def test_score_with_bound_entities(self):
        entities = [
            {"_type": "decision", "id": 1, "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        bound = {"decision:1"}
        result = score_entities(entities, bound_entity_keys=bound)
        assert result[0].score_breakdown["code_proximity"] == 1.0

    def test_score_without_bound_entities(self):
        entities = [
            {"_type": "decision", "id": 1, "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        result = score_entities(entities)
        assert result[0].score_breakdown["code_proximity"] == 0.0

    def test_score_with_semantic_scores(self):
        entities = [
            {"_type": "decision", "id": 1, "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        semantic = {"decision:1": 0.95}
        result = score_entities(entities, semantic_scores=semantic)
        assert result[0].score_breakdown["semantic_similarity"] == 0.95

    def test_scored_entity_to_dict(self):
        se = ScoredEntity(
            entity={"_type": "decision", "id": 1},
            entity_type="decision",
            entity_id=1,
            total_score=0.85,
            score_breakdown={"recency": 0.9},
            token_estimate=50,
        )
        d = se.to_dict()
        assert d["entity_type"] == "decision"
        assert d["total_score"] == 0.85
        assert d["token_estimate"] == 50

    def test_lifecycle_scores_coverage(self):
        """Ensure all expected statuses are covered."""
        expected = [
            "accepted", "discussed", "proposed", "active",
            "in_progress", "todo", "blocked", "done",
            "superseded", "deprecated",
        ]
        for status in expected:
            assert status in LIFECYCLE_SCORES

    def test_score_empty_entities(self):
        result = score_entities([])
        assert result == []

    def test_score_with_custom_weights(self):
        entities = [
            {"_type": "decision", "id": 1, "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        custom_weights = {
            "semantic_similarity": 0.0,
            "recency": 1.0,
            "reference_frequency": 0.0,
            "lifecycle_status": 0.0,
            "scope_priority": 0.0,
            "code_proximity": 0.0,
            "explicit_priority": 0.0,
        }
        result = score_entities(entities, custom_weights=custom_weights)
        assert len(result) == 1
        # With weight=1.0 on recency only, the total should equal the recency score
        assert abs(result[0].total_score - result[0].score_breakdown["recency"]) < 0.01

    def test_score_with_missing_updated_at(self):
        """Entity without updated_at should get a default recency score."""
        entities = [
            {"_type": "decision", "id": 1},
        ]
        result = score_entities(entities)
        assert len(result) == 1
        assert result[0].score_breakdown["recency"] == 0.5

    def test_score_with_visibility(self):
        entities = [
            {"_type": "decision", "id": 1, "visibility": "team", "updated_at": datetime.now(timezone.utc).isoformat()},
            {"_type": "decision", "id": 2, "visibility": "individual", "updated_at": datetime.now(timezone.utc).isoformat()},
        ]
        result = score_entities(entities)
        team_entity = next(r for r in result if r.entity_id == 1)
        indiv_entity = next(r for r in result if r.entity_id == 2)
        assert team_entity.score_breakdown["scope_priority"] > indiv_entity.score_breakdown["scope_priority"]
