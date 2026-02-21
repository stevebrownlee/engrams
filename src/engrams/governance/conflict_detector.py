"""Conflict detection engine for governance (Feature 1).

Runs whenever an individual-scope item is created or updated to check
against team-level governance rules and items.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from . import models as gov_models
from . import db_operations as gov_db

log = logging.getLogger(__name__)


def check_conflicts(
    workspace_id: str,
    item_type: str,
    item_data: Dict[str, Any],
    scope_id: Optional[int] = None
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
    if not scope or scope.scope_type != 'individual' or not scope.parent_scope_id:
        return result  # Only check individual scopes under team scopes

    team_scope_id = scope.parent_scope_id

    # 1. Tag-based matching
    tag_conflicts = _check_tag_conflicts(workspace_id, item_type, item_data, team_scope_id)
    result.conflicts.extend(tag_conflicts)

    # 2. Rule evaluation
    rule_result = _evaluate_governance_rules(workspace_id, item_type, item_data, team_scope_id)

    # Merge rule results
    if rule_result.has_conflict:
        result.has_conflict = True
        result.conflicts.extend(rule_result.conflicts)
        result.warnings.extend(rule_result.warnings)

        # Determine the strictest action
        if rule_result.action == 'block' or result.action == 'block':
            result.action = 'block'
        elif rule_result.action == 'warn' and result.action != 'block':
            result.action = 'warn'

    # If we have tag conflicts but no rule evaluation triggered, set warn
    if tag_conflicts and not rule_result.has_conflict:
        result.has_conflict = True
        result.action = 'warn'
        result.warnings.append(
            f"Item has overlapping tags with team-scope {item_type}(s). "
            "Review for potential conflicts."
        )

    return result


def _check_tag_conflicts(
    workspace_id: str,
    item_type: str,
    item_data: Dict[str, Any],
    team_scope_id: int
) -> List[Dict[str, Any]]:
    """Check for tag-based conflicts with team-level items."""
    conflicts: List[Dict[str, Any]] = []

    item_tags = item_data.get('tags', [])
    if not item_tags:
        return conflicts

    # Get team-scope items of the same type
    team_items = gov_db.get_team_items_by_type(workspace_id, item_type)

    for team_item in team_items:
        team_tags_raw = team_item.get('tags')
        if not team_tags_raw:
            continue

        try:
            team_tags = json.loads(team_tags_raw) if isinstance(team_tags_raw, str) else team_tags_raw
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(team_tags, list):
            continue

        # Find overlapping tags
        overlapping = set(item_tags) & set(team_tags)
        if overlapping:
            conflicts.append({
                "type": "tag_overlap",
                "team_item_type": item_type,
                "team_item_id": team_item.get('id'),
                "team_item_summary": team_item.get('summary', team_item.get('name', '')),
                "overlapping_tags": list(overlapping),
                "message": f"Tags {list(overlapping)} overlap with team-scope {item_type} #{team_item.get('id')}"
            })

    return conflicts


def _evaluate_governance_rules(
    workspace_id: str,
    item_type: str,
    item_data: Dict[str, Any],
    team_scope_id: int
) -> gov_models.ConflictCheckResult:
    """Evaluate all active governance rules for the team scope."""
    result = gov_models.ConflictCheckResult()

    rules = gov_db.get_governance_rules(workspace_id, team_scope_id, entity_type=item_type)

    for rule in rules:
        match = _does_rule_match(rule, item_data)
        if match:
            result.has_conflict = True
            conflict_info = {
                "type": "rule_violation",
                "rule_id": rule.id,
                "rule_type": rule.rule_type,
                "rule_description": rule.description,
                "match_details": match
            }
            result.conflicts.append(conflict_info)

            if rule.rule_type == 'hard_block':
                result.action = 'block'
                result.warnings.append(
                    f"BLOCKED: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"prevents this action."
                )
            elif rule.rule_type == 'soft_warn':
                if result.action != 'block':
                    result.action = 'warn'
                result.warnings.append(
                    f"WARNING: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"flagged a conflict."
                )
            elif rule.rule_type == 'allow_with_flag':
                if result.action not in ('block', 'warn'):
                    result.action = 'allow'
                result.warnings.append(
                    f"FLAGGED: Rule #{rule.id} ({rule.description or 'No description'}) "
                    f"- amendment will be proposed."
                )

    return result


def _does_rule_match(rule: gov_models.GovernanceRule, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    blocked_tags = rule_def.get('blocked_tags', [])
    if blocked_tags:
        item_tags = item_data.get('tags', []) or []
        found_blocked = set(blocked_tags) & set(item_tags)
        if found_blocked:
            match_details['blocked_tags_found'] = list(found_blocked)

    # Check required tags (absence is a violation)
    required_tags = rule_def.get('required_tags', [])
    if required_tags:
        item_tags = item_data.get('tags', []) or []
        missing = set(required_tags) - set(item_tags)
        if missing:
            match_details['required_tags_missing'] = list(missing)

    # Check blocked keywords in text fields
    blocked_keywords = rule_def.get('blocked_keywords', [])
    if blocked_keywords:
        text_fields = ['summary', 'rationale', 'description', 'implementation_details', 'name']
        item_text = ' '.join(
            str(item_data.get(f, '')) for f in text_fields if item_data.get(f)
        ).lower()
        found_keywords = [kw for kw in blocked_keywords if kw.lower() in item_text]
        if found_keywords:
            match_details['blocked_keywords_found'] = found_keywords

    # Check required keywords
    required_keywords = rule_def.get('required_keywords', [])
    if required_keywords:
        text_fields = ['summary', 'rationale', 'description', 'implementation_details', 'name']
        item_text = ' '.join(
            str(item_data.get(f, '')) for f in text_fields if item_data.get(f)
        ).lower()
        missing_keywords = [kw for kw in required_keywords if kw.lower() not in item_text]
        if missing_keywords:
            match_details['required_keywords_missing'] = missing_keywords

    return match_details if match_details else None
