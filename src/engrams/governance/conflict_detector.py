# Copyright 2025 Scott McLeod (contextportal@gmail.com)
# Copyright 2025 Steve Brownlee (steve@stevebrownlee.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Conflict detection engine for governance (Feature 1).

Runs whenever an individual-scope item is created or updated to check
against team-level governance rules and items.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from . import db_operations as gov_db
from . import models as gov_models
from ..db import database as db

log = logging.getLogger(__name__)


def check_conflicts(
    workspace_id: str,
    item_type: str,
    item_data: Dict[str, Any],
    scope_id: Optional[int] = None,
) -> gov_models.ConflictCheckResult:
    """
    Run the conflict detection pipeline for a new/updated item.

    Args:
        workspace_id: The workspace identifier.
        item_type: Entity type ('decision', 'system_pattern', etc.).
        item_data: Dictionary of the item's fields (summary, tags, etc.).
        scope_id: The scope this item belongs to.

    Returns:
        ConflictCheckResult indicating whether conflicts were found and
        what action should be taken.
    """
    result = gov_models.ConflictCheckResult()

    if scope_id is None:
        return result  # No scope assigned, no governance check needed

    # Check if this scope is an individual scope with a parent team scope
    scope = gov_db.get_scope_by_id(workspace_id, scope_id)
    if not scope or scope.scope_type != "individual" or not scope.parent_scope_id:
        return result  # Only check individual scopes under team scopes

    team_scope_id = scope.parent_scope_id

    # 1. Tag-based matching
    tag_conflicts = _check_tag_conflicts(
        workspace_id, item_type, item_data, team_scope_id
    )
    result.conflicts.extend(tag_conflicts)

    # 2. Rule evaluation
    rule_result = _evaluate_governance_rules(
        workspace_id, item_type, item_data, team_scope_id
    )

    # Merge rule results
    if rule_result.has_conflict:
        result.has_conflict = True
        result.conflicts.extend(rule_result.conflicts)
        result.warnings.extend(rule_result.warnings)

        # Determine the strictest action
        if rule_result.action == "block" or result.action == "block":
            result.action = "block"
        elif rule_result.action == "warn" and result.action != "block":
            result.action = "warn"

    # If we have tag conflicts but no rule evaluation triggered, set warn
    if tag_conflicts and not rule_result.has_conflict:
        result.has_conflict = True
        result.action = "warn"
        result.warnings.append(
            f"Item has overlapping tags with team-scope {item_type}(s). "
            "Review for potential conflicts."
        )

    return result


def _check_tag_conflicts(
    workspace_id: str, item_type: str, item_data: Dict[str, Any], team_scope_id: int
) -> List[Dict[str, Any]]:
    """Check for tag-based conflicts with team-level items."""
    conflicts: List[Dict[str, Any]] = []

    item_tags = item_data.get("tags", [])
    if not item_tags:
        return conflicts

    # Get team-scope items of the same type
    team_items = gov_db.get_team_items_by_type(workspace_id, item_type)

    for team_item in team_items:
        team_tags_raw = team_item.get("tags")
        if not team_tags_raw:
            continue

        try:
            team_tags = (
                json.loads(team_tags_raw)
                if isinstance(team_tags_raw, str)
                else team_tags_raw
            )
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(team_tags, list):
            continue

        # Find overlapping tags
        overlapping = set(item_tags) & set(team_tags)
        if overlapping:
            conflicts.append(
                {
                    "type": "tag_overlap",
                    "team_item_type": item_type,
                    "team_item_id": team_item.get("id"),
                    "team_item_summary": team_item.get(
                        "summary", team_item.get("name", "")
                    ),
                    "overlapping_tags": list(overlapping),
                    "message": f"Tags {list(overlapping)} overlap with team-scope {item_type} #{team_item.get('id')}",
                }
            )

    return conflicts


def _evaluate_governance_rules(
    workspace_id: str, item_type: str, item_data: Dict[str, Any], team_scope_id: int
) -> gov_models.ConflictCheckResult:
    """Evaluate all active governance rules for the team scope."""
    result = gov_models.ConflictCheckResult()

    rules = gov_db.get_governance_rules(
        workspace_id, team_scope_id, entity_type=item_type
    )

    for rule in rules:
        match = _does_rule_match(rule, item_data)
        if match:
            result.has_conflict = True
            conflict_info = {
                "type": "rule_violation",
                "rule_id": rule.id,
                "rule_type": rule.rule_type,
                "rule_description": rule.description,
                "match_details": match,
            }
            result.conflicts.append(conflict_info)

            if rule.rule_type == "hard_block":
                result.action = "block"
                result.warnings.append(
                    f"BLOCKED: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"prevents this action."
                )
            elif rule.rule_type == "soft_warn":
                if result.action != "block":
                    result.action = "warn"
                result.warnings.append(
                    f"WARNING: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"flagged a conflict."
                )
            elif rule.rule_type == "allow_with_flag":
                if result.action not in ("block", "warn"):
                    result.action = "allow"
                result.warnings.append(
                    f"FLAGGED: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"- amendment will be proposed."
                )

    return result


def _does_rule_match(
    rule: gov_models.GovernanceRule, item_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Check if a governance rule matches against item data.

    Rule definitions can contain:
    - "blocked_tags": list of tags that are forbidden
    - "required_tags": list of tags that must be present
    - "blocked_keywords": list of keywords that can't appear in summary/description
    - "required_keywords": list of keywords that must appear

    Returns match details dict if matched, None otherwise.
    """
    rule_def = rule.rule_definition
    match_details: Dict[str, Any] = {}

    # Check blocked tags
    blocked_tags = rule_def.get("blocked_tags", [])
    if blocked_tags:
        item_tags = item_data.get("tags", []) or []
        found_blocked = set(blocked_tags) & set(item_tags)
        if found_blocked:
            match_details["blocked_tags_found"] = list(found_blocked)

    # Check required tags (absence is a violation)
    required_tags = rule_def.get("required_tags", [])
    if required_tags:
        item_tags = item_data.get("tags", []) or []
        missing = set(required_tags) - set(item_tags)
        if missing:
            match_details["required_tags_missing"] = list(missing)

    # Check blocked keywords in text fields
    blocked_keywords = rule_def.get("blocked_keywords", [])
    if blocked_keywords:
        text_fields = [
            "summary",
            "rationale",
            "description",
            "implementation_details",
            "name",
        ]
        item_text = " ".join(
            str(item_data.get(f, "")) for f in text_fields if item_data.get(f)
        ).lower()
        found_keywords = [kw for kw in blocked_keywords if kw.lower() in item_text]
        if found_keywords:
            match_details["blocked_keywords_found"] = found_keywords

    # Check required keywords
    required_keywords = rule_def.get("required_keywords", [])
    if required_keywords:
        text_fields = [
            "summary",
            "rationale",
            "description",
            "implementation_details",
            "name",
        ]
        item_text = " ".join(
            str(item_data.get(f, "")) for f in text_fields if item_data.get(f)
        ).lower()
        missing_keywords = [
            kw for kw in required_keywords if kw.lower() not in item_text
        ]
        if missing_keywords:
            match_details["required_keywords_missing"] = missing_keywords

    return match_details if match_details else None


def check_decision_conflicts(
    workspace_id: str,
    item_type: str,
    item_data: Dict[str, Any],
) -> gov_models.ConflictCheckResult:
    """
    Check a proposed item against all accepted decisions in the workspace.

    Unlike check_conflicts(), this does NOT require scopes or governance rules.
    It directly scans the decisions table for tag overlap and keyword conflicts.

    This is the post-write safety net — it runs after every write to flag
    potential conflicts with accepted team decisions.

    Args:
        workspace_id: The workspace identifier.
        item_type: Entity type being written ('decision', 'system_pattern', etc.).
        item_data: Dictionary of the item's fields (summary, tags, rationale, etc.).

    Returns:
        ConflictCheckResult with action='warn' if conflicts found (never 'block' —
        the post-write path uses warnings only since the write already happened).
    """
    result = gov_models.ConflictCheckResult()
    result.action = "warn"  # Post-write path only warns, never blocks

    try:
        # Fetch all decisions from the workspace
        decisions = db.get_decisions(workspace_id, limit=None)
        if not decisions:
            return result  # No decisions to check against

        item_tags = item_data.get("tags", []) or []
        item_summary = (item_data.get("summary") or "").lower()
        item_rationale = (item_data.get("rationale") or "").lower()
        item_description = (item_data.get("description") or "").lower()
        item_text = f"{item_summary} {item_rationale} {item_description}".strip()

        for decision in decisions:
            # Skip if decision has no tags or summary
            if not decision.tags or not decision.summary:
                continue

            # 1. Check for tag overlap
            decision_tags = decision.tags if isinstance(decision.tags, list) else []
            overlapping_tags = set(item_tags) & set(decision_tags)

            if overlapping_tags:
                # Tag overlap detected — check if decision suggests a constraint
                decision_summary = (decision.summary or "").lower()
                decision_rationale = (decision.rationale or "").lower()
                decision_text = f"{decision_summary} {decision_rationale}".strip()

                # 2. Check for keyword conflicts
                # Extract key terms from decision and check for contradictions
                has_keyword_conflict = _check_keyword_conflict(
                    decision_text, item_text, overlapping_tags
                )

                if overlapping_tags or has_keyword_conflict:
                    result.has_conflict = True
                    conflict_info = {
                        "type": "decision_conflict",
                        "decision_id": decision.id,
                        "decision_summary": decision.summary,
                        "decision_uuid": decision.uuid,
                        "overlapping_tags": list(overlapping_tags),
                        "message": f"Potential conflict with Decision #{decision.id}: '{decision.summary}'",
                    }
                    result.conflicts.append(conflict_info)
                    result.warnings.append(
                        f"WARNING: This item may conflict with accepted Decision #{decision.id}: "
                        f"'{decision.summary}'. Review before proceeding."
                    )

        return result

    except Exception as e:
        # Non-fatal — log and return empty result
        log.warning("Decision conflict check failed (non-fatal): %s", e)
        return gov_models.ConflictCheckResult()


def _check_keyword_conflict(
    decision_text: str, item_text: str, overlapping_tags: set
) -> bool:
    """
    Check if item text contains contradictory keywords relative to decision text.

    Simple approach: extract key terms from decision and check if item text
    references the same domain (via tag overlap) but with different technology terms.

    Args:
        decision_text: Lowercased decision summary + rationale.
        item_text: Lowercased item summary + rationale + description.
        overlapping_tags: Tags that overlap between decision and item.

    Returns:
        True if a keyword conflict is detected, False otherwise.
    """
    if not overlapping_tags or not decision_text or not item_text:
        return False

    # Extract words from decision text (simple tokenization)
    decision_words = set(decision_text.split())
    item_words = set(item_text.split())

    # Common technology/architecture keywords that often conflict
    conflict_pairs = [
        ("sqlite", "postgresql"),
        ("postgresql", "sqlite"),
        ("mysql", "postgresql"),
        ("mysql", "sqlite"),
        ("mongodb", "postgresql"),
        ("mongodb", "sqlite"),
        ("rest", "graphql"),
        ("graphql", "rest"),
        ("sync", "async"),
        ("async", "sync"),
        ("monolith", "microservice"),
        ("microservice", "monolith"),
    ]

    # Check if decision mentions one technology and item mentions another
    for tech1, tech2 in conflict_pairs:
        if tech1 in decision_words and tech2 in item_words:
            return True
        if tech2 in decision_words and tech1 in item_words:
            return True

    # Also check for explicit contradictions like "switch", "change", "replace"
    contradiction_keywords = ["switch", "change", "replace", "migrate", "convert"]
    if any(kw in item_words for kw in contradiction_keywords):
        # If item mentions switching/changing and overlaps with decision tags,
        # it might be proposing a change to an accepted decision
        return True

    return False
