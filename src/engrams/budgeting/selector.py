"""Budget-constrained context selection for Engrams entities (Feature 3).

Implements a greedy selection algorithm that picks the highest-scored entities
that fit within a specified token budget.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .scorer import ScoredEntity
from .estimator import estimate_tokens

log = logging.getLogger(__name__)


@dataclass
class ContextBudgetResult:
    """Result of budget-constrained context selection."""

    selected: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens_used: int = 0
    budget_remaining: int = 0
    excluded_count: int = 0
    excluded_top: List[Dict[str, Any]] = field(default_factory=list)
    format_used: str = "standard"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected": self.selected,
            "total_tokens_used": self.total_tokens_used,
            "budget_remaining": self.budget_remaining,
            "excluded_count": self.excluded_count,
            "excluded_top": self.excluded_top,
            "format_used": self.format_used,
        }


def select_context(
    candidates: List[ScoredEntity],
    token_budget: int,
    must_include: Optional[List[Tuple[str, int]]] = None,
    format_preference: str = "standard",
) -> ContextBudgetResult:
    """Select entities within a token budget using greedy algorithm.

    Args:
        candidates: Scored entities (will be sorted by relevance if not already).
        token_budget: Maximum token budget.
        must_include: List of (entity_type, entity_id) tuples that must be included.
        format_preference: Preferred entity format ('compact', 'standard', 'verbose').

    Returns:
        ContextBudgetResult with selected entities and budget metadata.
    """
    must_include = must_include or []
    must_include_keys = {f"{t}:{i}" for t, i in must_include}

    # Sort candidates by total_score descending to ensure greedy selection picks highest scores
    sorted_candidates = sorted(candidates, key=lambda c: c.total_score, reverse=True)

    result = ContextBudgetResult(
        budget_remaining=token_budget,
        format_used=format_preference,
    )

    # Determine format based on budget tightness
    # If budget is very tight, downgrade to compact
    total_estimated = sum(c.token_estimate for c in sorted_candidates)
    if total_estimated > token_budget * 3 and format_preference != "compact":
        format_preference = "compact"
        result.format_used = "compact"
        # Re-estimate tokens with compact format
        for c in sorted_candidates:
            c.token_estimate = estimate_tokens(c.entity, format="compact")

    selected_keys: set = set()

    # Phase 1: Include must-include entities first
    for candidate in sorted_candidates:
        key = f"{candidate.entity_type}:{candidate.entity_id}"
        if key in must_include_keys and key not in selected_keys:
            token_cost = estimate_tokens(
                candidate.entity, format=format_preference
            )
            # Must-include items are added even if they blow the budget
            result.selected.append(
                {
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.entity_id,
                    "entity": candidate.entity,
                    "total_score": round(candidate.total_score, 4),
                    "score_breakdown": {
                        k: round(v, 4)
                        for k, v in candidate.score_breakdown.items()
                    },
                    "token_cost": token_cost,
                    "format": format_preference,
                }
            )
            result.total_tokens_used += token_cost
            result.budget_remaining -= token_cost
            selected_keys.add(key)

    # Phase 2: Greedily select remaining entities by score
    excluded: List[Dict[str, Any]] = []
    for candidate in sorted_candidates:
        key = f"{candidate.entity_type}:{candidate.entity_id}"
        if key in selected_keys:
            continue

        # Use the pre-computed token estimate from the candidate
        # which already accounts for the format preference determined earlier
        token_cost = candidate.token_estimate
        used_format = format_preference

        if token_cost <= result.budget_remaining:
            result.selected.append(
                {
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.entity_id,
                    "entity": candidate.entity,
                    "total_score": round(candidate.total_score, 4),
                    "score_breakdown": {
                        k: round(v, 4)
                        for k, v in candidate.score_breakdown.items()
                    },
                    "token_cost": token_cost,
                    "format": used_format,
                }
            )
            result.total_tokens_used += token_cost
            result.budget_remaining -= token_cost
            selected_keys.add(key)
        else:
            excluded.append(
                {
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.entity_id,
                    "total_score": round(candidate.total_score, 4),
                    "token_cost": token_cost,
                }
            )

    result.excluded_count = len(excluded)
    result.excluded_top = excluded[:5]  # Top 5 excluded by score

    return result


def estimate_context_size(
    candidates: List[ScoredEntity],
) -> Dict[str, Any]:
    """Preview how much context is available and recommended budget tiers.

    Args:
        candidates: Scored entities.

    Returns:
        Dict with entity counts, token estimates, and budget tier recommendations.
    """
    compact_tokens = sum(
        estimate_tokens(c.entity, format="compact") for c in candidates
    )
    standard_tokens = sum(
        estimate_tokens(c.entity, format="standard") for c in candidates
    )
    verbose_tokens = sum(
        estimate_tokens(c.entity, format="verbose") for c in candidates
    )

    # Count by type
    type_counts: Dict[str, int] = {}
    for c in candidates:
        type_counts[c.entity_type] = type_counts.get(c.entity_type, 0) + 1

    return {
        "total_entities": len(candidates),
        "entities_by_type": type_counts,
        "token_estimates": {
            "compact": compact_tokens,
            "standard": standard_tokens,
            "verbose": verbose_tokens,
        },
        "recommended_budgets": {
            "minimal": max(500, compact_tokens // 3),
            "standard": max(2000, standard_tokens // 2),
            "comprehensive": verbose_tokens,
        },
    }
