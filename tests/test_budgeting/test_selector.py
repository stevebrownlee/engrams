"""Tests for budget-constrained selection (Feature 3)."""

from engrams.budgeting.scorer import ScoredEntity
from engrams.budgeting.selector import select_context, estimate_context_size, ContextBudgetResult


class TestSelector:
    def _make_scored(self, entity_type, entity_id, score, tokens):
        return ScoredEntity(
            entity={"_type": entity_type, "id": entity_id, "summary": f"Entity {entity_id}"},
            entity_type=entity_type,
            entity_id=entity_id,
            total_score=score,
            score_breakdown={"recency": score},
            token_estimate=tokens,
        )

    def test_select_within_budget(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
            self._make_scored("decision", 2, 0.7, 100),
            self._make_scored("decision", 3, 0.5, 100),
        ]
        result = select_context(candidates, token_budget=250)
        assert isinstance(result, ContextBudgetResult)
        assert len(result.selected) == 2  # Budget fits 2 of 3
        assert result.total_tokens_used <= 250
        assert result.excluded_count == 1

    def test_select_all_fit(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 50),
            self._make_scored("decision", 2, 0.7, 50),
        ]
        result = select_context(candidates, token_budget=1000)
        assert len(result.selected) == 2
        assert result.excluded_count == 0
        assert result.budget_remaining > 0

    def test_select_zero_budget(self):
        candidates = [self._make_scored("decision", 1, 0.9, 100)]
        result = select_context(candidates, token_budget=0)
        assert len(result.selected) == 0

    def test_select_empty_candidates(self):
        result = select_context([], token_budget=1000)
        assert len(result.selected) == 0
        assert result.total_tokens_used == 0
        assert result.excluded_count == 0

    def test_must_include(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
            self._make_scored("decision", 2, 0.3, 100),
        ]
        result = select_context(candidates, token_budget=150, must_include=[("decision", 2)])
        # Must-include item should be included even with lower score
        included_ids = [s["entity_id"] for s in result.selected]
        assert 2 in included_ids

    def test_must_include_always_added(self):
        """Must-include items are added even if they exceed budget."""
        candidates = [
            self._make_scored("decision", 1, 0.9, 500),
        ]
        result = select_context(candidates, token_budget=10, must_include=[("decision", 1)])
        included_ids = [s["entity_id"] for s in result.selected]
        assert 1 in included_ids

    def test_highest_scored_selected_first(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
            self._make_scored("decision", 2, 0.3, 100),
            self._make_scored("decision", 3, 0.6, 100),
        ]
        result = select_context(candidates, token_budget=250)
        # Should select entities 1 and 3 (highest scores)
        included_ids = [s["entity_id"] for s in result.selected]
        assert 1 in included_ids
        assert 3 in included_ids

    def test_result_to_dict(self):
        result = ContextBudgetResult(selected=[], total_tokens_used=0, budget_remaining=1000)
        d = result.to_dict()
        assert "selected" in d
        assert "budget_remaining" in d
        assert "total_tokens_used" in d
        assert "excluded_count" in d
        assert "excluded_top" in d
        assert "format_used" in d

    def test_excluded_top_limited(self):
        """Excluded top should show at most 5 entries."""
        candidates = [
            self._make_scored("decision", i, 0.1 * i, 100)
            for i in range(1, 11)
        ]
        result = select_context(candidates, token_budget=100)
        assert len(result.excluded_top) <= 5


class TestEstimateContextSize:
    def _make_scored(self, entity_type, entity_id, score, tokens):
        return ScoredEntity(
            entity={"_type": entity_type, "id": entity_id, "summary": f"Entity {entity_id}"},
            entity_type=entity_type,
            entity_id=entity_id,
            total_score=score,
            score_breakdown={"recency": score},
            token_estimate=tokens,
        )

    def test_estimate_context_size(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
            self._make_scored("system_pattern", 2, 0.7, 200),
        ]
        result = estimate_context_size(candidates)
        assert result["total_entities"] == 2
        assert "decision" in result["entities_by_type"]
        assert "system_pattern" in result["entities_by_type"]
        assert "token_estimates" in result
        assert "recommended_budgets" in result

    def test_estimate_empty_candidates(self):
        result = estimate_context_size([])
        assert result["total_entities"] == 0
        assert result["entities_by_type"] == {}

    def test_estimate_token_estimates_have_all_formats(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
        ]
        result = estimate_context_size(candidates)
        assert "compact" in result["token_estimates"]
        assert "standard" in result["token_estimates"]
        assert "verbose" in result["token_estimates"]

    def test_recommended_budgets_have_tiers(self):
        candidates = [
            self._make_scored("decision", 1, 0.9, 100),
        ]
        result = estimate_context_size(candidates)
        assert "minimal" in result["recommended_budgets"]
        assert "standard" in result["recommended_budgets"]
        assert "comprehensive" in result["recommended_budgets"]
