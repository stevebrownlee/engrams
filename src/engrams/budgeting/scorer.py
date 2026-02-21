"""Relevance scoring logic for Engrams entities (Feature 3).

Each entity receives a composite relevance score (0.0 to 1.0) based on
weighted factors: semantic similarity, recency, reference frequency,
lifecycle status, scope priority, code proximity, and explicit priority.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .profiles import get_profile_weights

log = logging.getLogger(__name__)

# Lifecycle status scoring map (higher = more relevant)
LIFECYCLE_SCORES: Dict[str, float] = {
    "accepted": 1.0,
    "discussed": 0.8,
    "proposed": 0.6,
    "active": 1.0,
    "in_progress": 0.9,
    "todo": 0.7,
    "blocked": 0.6,
    "done": 0.3,
    "superseded": 0.1,
    "deprecated": 0.05,
}

# Visibility / scope scoring
SCOPE_SCORES: Dict[str, float] = {
    "team": 1.0,
    "workspace": 0.7,
    "individual": 0.5,
    "proposed": 0.3,
}


class ScoredEntity:
    """An entity with its computed relevance score and breakdown."""

    __slots__ = (
        "entity", "entity_type", "entity_id", "total_score",
        "score_breakdown", "token_estimate",
    )

    def __init__(
        self,
        entity: Dict[str, Any],
        entity_type: str,
        entity_id: int,
        total_score: float = 0.0,
        score_breakdown: Optional[Dict[str, float]] = None,
        token_estimate: int = 0,
    ):
        self.entity = entity
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.total_score = total_score
        self.score_breakdown = score_breakdown or {}
        self.token_estimate = token_estimate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity": self.entity,
            "total_score": round(self.total_score, 4),
            "score_breakdown": {k: round(v, 4) for k, v in self.score_breakdown.items()},
            "token_estimate": self.token_estimate,
        }


def score_entities(
    entities: List[Dict[str, Any]],
    task_description: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
    profile: str = "task_focused",
    custom_weights: Optional[Dict[str, float]] = None,
    workspace_id: Optional[str] = None,
    link_counts: Optional[Dict[str, int]] = None,
    bound_entity_keys: Optional[set] = None,
    semantic_scores: Optional[Dict[str, float]] = None,
) -> List[ScoredEntity]:
    """Score a list of Engrams entities for relevance.

    Args:
        entities: List of entity dicts (must include '_type' and 'id' keys).
        task_description: Current task description for semantic similarity.
        file_paths: Files being edited (for code proximity scoring).
        profile: Scoring profile name.
        custom_weights: Override weights (used when profile='custom').
        workspace_id: Workspace ID for database lookups (unused in pure scoring).
        link_counts: Pre-computed dict of 'type:id' -> link count for centrality.
        bound_entity_keys: Pre-computed set of 'type:id' keys with code bindings.
        semantic_scores: Pre-computed dict of 'type:id' -> similarity score (0-1).

    Returns:
        List of ScoredEntity objects sorted by total_score descending.
    """
    weights = custom_weights if custom_weights else get_profile_weights(profile)
    link_counts = link_counts or {}
    bound_entity_keys = bound_entity_keys or set()
    semantic_scores = semantic_scores or {}

    # Find max link count for normalization
    max_links = max(link_counts.values()) if link_counts else 1

    scored = []
    now = datetime.now(timezone.utc)

    for entity in entities:
        entity_type = entity.get("_type", "unknown")
        entity_id = entity.get("id", 0)
        key = f"{entity_type}:{entity_id}"
        breakdown: Dict[str, float] = {}

        # 1. Semantic similarity
        breakdown["semantic_similarity"] = semantic_scores.get(key, 0.0)

        # 2. Recency - exponential decay based on updated_at
        updated_at_str = entity.get("updated_at") or entity.get("created_at")
        if updated_at_str:
            try:
                if isinstance(updated_at_str, str):
                    updated_at = datetime.fromisoformat(
                        updated_at_str.replace("Z", "+00:00")
                    )
                elif isinstance(updated_at_str, datetime):
                    updated_at = (
                        updated_at_str
                        if updated_at_str.tzinfo
                        else updated_at_str.replace(tzinfo=timezone.utc)
                    )
                else:
                    updated_at = now
                days_old = max((now - updated_at).total_seconds() / 86400, 0)
                # Exponential decay: half-life of 30 days
                breakdown["recency"] = math.exp(-0.693 * days_old / 30)
            except (ValueError, TypeError):
                breakdown["recency"] = 0.5
        else:
            breakdown["recency"] = 0.5

        # 3. Reference frequency (graph centrality)
        link_count = link_counts.get(key, 0)
        breakdown["reference_frequency"] = (
            link_count / max_links if max_links > 0 else 0.0
        )

        # 4. Lifecycle status
        status = (
            entity.get("lifecycle_status") or entity.get("status") or "active"
        )
        breakdown["lifecycle_status"] = LIFECYCLE_SCORES.get(
            status.lower(), 0.5
        )

        # 5. Scope priority
        visibility = entity.get("visibility", "workspace")
        breakdown["scope_priority"] = SCOPE_SCORES.get(visibility, 0.7)

        # 6. Code proximity
        breakdown["code_proximity"] = 1.0 if key in bound_entity_keys else 0.0

        # 7. Explicit priority
        priority = entity.get("priority")
        if isinstance(priority, (int, float)):
            breakdown["explicit_priority"] = min(
                max(float(priority) / 10.0, 0.0), 1.0
            )
        else:
            breakdown["explicit_priority"] = 0.5

        # Compute weighted total
        total = sum(
            weights.get(factor, 0.0) * score
            for factor, score in breakdown.items()
        )
        total = min(max(total, 0.0), 1.0)

        # Estimate tokens
        from .estimator import estimate_tokens

        token_est = estimate_tokens(entity, format="compact")

        scored.append(
            ScoredEntity(
                entity=entity,
                entity_type=entity_type,
                entity_id=entity_id,
                total_score=total,
                score_breakdown=breakdown,
                token_estimate=token_est,
            )
        )

    scored.sort(key=lambda s: s.total_score, reverse=True)
    return scored
