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

"""Briefing generation logic for project onboarding (Feature 4)."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .templates import BRIEFING_SECTIONS, get_default_budget, get_sections_for_level

log = logging.getLogger(__name__)

# Staleness threshold in days
DEFAULT_STALE_DAYS = 30


def generate_briefing(
    workspace_id: str,
    level: str = "overview",
    token_budget: Optional[int] = None,
    sections: Optional[List[str]] = None,
    scope_id: Optional[int] = None,
    stale_threshold_days: int = DEFAULT_STALE_DAYS,
) -> Dict[str, Any]:
    """Generate a project briefing at the specified level.

    Args:
        workspace_id: Workspace to generate briefing for.
        level: Briefing depth level (executive/overview/detailed/comprehensive).
        token_budget: Max tokens for the briefing. Defaults per level.
        sections: Optional list of section IDs to include.
        scope_id: Optional scope ID for filtering (Feature 1).
        stale_threshold_days: Days after which data is considered stale.

    Returns:
        Structured briefing dict with sections, staleness info, and coverage stats.
    """
    from ..db import database

    if token_budget is None:
        token_budget = get_default_budget(level)

    applicable_sections = get_sections_for_level(level, sections)
    now = datetime.now(timezone.utc)

    briefing_sections: List[Dict[str, Any]] = []
    total_decisions = 0
    included_decisions = 0
    total_patterns = 0
    included_patterns = 0

    for section_def in applicable_sections:
        section_id = section_def["id"]
        requires = section_def.get("requires_feature")

        # Check feature availability
        if requires:
            if not _check_feature_available(workspace_id, requires):
                continue

        try:
            content, entity_count, updated_at = _fetch_section_data(
                workspace_id, section_id, section_def["source"], scope_id
            )

            # Track decision/pattern counts for coverage
            if section_id == "all_decisions":
                total_decisions = entity_count
                included_decisions = entity_count
            elif section_id == "key_decisions":
                included_decisions = entity_count
            elif section_id == "patterns":
                total_patterns = entity_count
                included_patterns = entity_count

            # Calculate staleness
            staleness_days = _compute_staleness_days(now, updated_at)

            briefing_sections.append(
                {
                    "id": section_id,
                    "title": section_def["title"],
                    "content": content,
                    "staleness_days": staleness_days,
                    "entity_count": entity_count,
                    "is_stale": (
                        staleness_days is not None
                        and staleness_days > stale_threshold_days
                    ),
                }
            )
        except Exception as e:
            log.warning("Failed to fetch section '%s': %s", section_id, e)
            briefing_sections.append(
                {
                    "id": section_id,
                    "title": section_def["title"],
                    "content": {"error": str(e)},
                    "staleness_days": None,
                    "entity_count": 0,
                    "is_stale": False,
                }
            )

    # Get total counts for coverage stats if not already gathered
    if total_decisions == 0:
        try:
            all_decisions = database.get_decisions(workspace_id, limit=1000)
            total_decisions = len(all_decisions)
        except Exception:
            pass
    if total_patterns == 0:
        try:
            all_patterns = database.get_system_patterns(workspace_id)
            total_patterns = len(all_patterns)
        except Exception:
            pass

    return {
        "level": level,
        "generated_at": now.isoformat(),
        "token_budget": token_budget,
        "sections": briefing_sections,
        "data_coverage": {
            "total_decisions": total_decisions,
            "included_decisions": included_decisions,
            "total_patterns": total_patterns,
            "included_patterns": included_patterns,
            "note": (
                "Use level='detailed' or increase token_budget for fuller coverage"
                if level in ("executive", "overview")
                else None
            ),
        },
    }


def check_briefing_staleness(
    workspace_id: str,
    stale_threshold_days: int = DEFAULT_STALE_DAYS,
) -> Dict[str, Any]:
    """Check how fresh the briefing data is per section.

    Args:
        workspace_id: Workspace to check.
        stale_threshold_days: Days after which data is stale.

    Returns:
        Dict with per-section staleness info and a stale count.
    """
    now = datetime.now(timezone.utc)

    all_sections = get_sections_for_level("comprehensive")
    staleness_info: List[Dict[str, Any]] = []

    for section_def in all_sections:
        section_id = section_def["id"]
        requires = section_def.get("requires_feature")

        if requires and not _check_feature_available(workspace_id, requires):
            staleness_info.append(
                {
                    "section_id": section_id,
                    "title": section_def["title"],
                    "status": "feature_unavailable",
                    "staleness_days": None,
                    "is_stale": False,
                }
            )
            continue

        try:
            _, _, updated_at = _fetch_section_data(
                workspace_id, section_id, section_def["source"], scope_id=None
            )
            staleness_days = _compute_staleness_days(now, updated_at)

            staleness_info.append(
                {
                    "section_id": section_id,
                    "title": section_def["title"],
                    "status": "available",
                    "staleness_days": staleness_days,
                    "is_stale": (
                        staleness_days is not None
                        and staleness_days > stale_threshold_days
                    ),
                }
            )
        except Exception as e:
            staleness_info.append(
                {
                    "section_id": section_id,
                    "title": section_def["title"],
                    "status": "error",
                    "staleness_days": None,
                    "is_stale": False,
                    "error": str(e),
                }
            )

    return {
        "stale_threshold_days": stale_threshold_days,
        "sections": staleness_info,
        "stale_count": sum(1 for s in staleness_info if s.get("is_stale")),
    }


def get_section_detail(
    workspace_id: str,
    section_id: str,
    token_budget: Optional[int] = None,
    scope_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Get detailed content for a specific briefing section.

    Args:
        workspace_id: Workspace to query.
        section_id: ID of the section to expand.
        token_budget: Optional token budget (reserved for future use).
        scope_id: Optional scope filter.

    Returns:
        Dict with section content or error.
    """
    section_def = None
    for s in BRIEFING_SECTIONS:
        if s["id"] == section_id:
            section_def = s
            break

    if not section_def:
        return {"status": "error", "error": f"Unknown section: {section_id}"}

    requires = section_def.get("requires_feature")
    if requires and not _check_feature_available(workspace_id, requires):
        return {
            "status": "error",
            "error": f"Required feature '{requires}' not available",
        }

    try:
        content, entity_count, updated_at = _fetch_section_data(
            workspace_id, section_id, section_def["source"], scope_id
        )
        return {
            "status": "success",
            "section_id": section_id,
            "title": section_def["title"],
            "description": section_def["description"],
            "content": content,
            "entity_count": entity_count,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_staleness_days(now: datetime, updated_at: Any) -> Optional[int]:
    """Compute the number of days since *updated_at*.

    Returns ``None`` when the timestamp cannot be parsed.
    """
    if updated_at is None:
        return None
    try:
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if not getattr(updated_at, "tzinfo", None):
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return (now - updated_at).days
    except (ValueError, TypeError):
        return None


def _check_feature_available(workspace_id: str, feature: str) -> bool:
    """Check if a feature's tables exist in the database.

    Args:
        workspace_id: Workspace identifier.
        feature: Feature name (``governance`` or ``bindings``).

    Returns:
        True if the feature tables exist, False otherwise.
    """
    from ..db import database

    table_for_feature = {
        "governance": "context_scopes",
        "bindings": "code_bindings",
    }
    table = table_for_feature.get(feature)
    if table is None:
        return False

    try:
        conn = database.get_db_connection(workspace_id)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        result = cursor.fetchone() is not None
        cursor.close()
        return result
    except Exception:
        return False


def _most_recent_date(*dates: Any) -> Any:
    """Return the most recent non-None date from the arguments."""
    best = None
    for d in dates:
        if d is None:
            continue
        if best is None or str(d) > str(best):
            best = d
    return best


def _entity_to_dict(entity: Any) -> Dict[str, Any]:
    """Safely convert an entity (Pydantic model or dict) to a dict."""
    if hasattr(entity, "model_dump"):
        return entity.model_dump(mode="json")
    if isinstance(entity, dict):
        return entity
    return dict(entity)


def _fetch_section_data(
    workspace_id: str,
    section_id: str,
    source: str,
    scope_id: Optional[int],
) -> tuple:
    """Fetch data for a briefing section.

    Returns:
        Tuple of ``(content, entity_count, most_recent_updated_at)``.
    """
    from ..db import database

    # ------------------------------------------------------------------
    # project_identity  – Product Context
    # ------------------------------------------------------------------
    if section_id == "project_identity":
        ctx = database.get_product_context(workspace_id)
        content = ctx.content if hasattr(ctx, "content") else {}
        updated_at = getattr(ctx, "updated_at", None)
        return content, (1 if content else 0), updated_at

    # ------------------------------------------------------------------
    # current_status  – Active Context
    # ------------------------------------------------------------------
    if section_id == "current_status":
        ctx = database.get_active_context(workspace_id)
        content = ctx.content if hasattr(ctx, "content") else {}
        updated_at = getattr(ctx, "updated_at", None)
        return content, (1 if content else 0), updated_at

    # ------------------------------------------------------------------
    # architecture  – Product Context + top system patterns
    # ------------------------------------------------------------------
    if section_id == "architecture":
        ctx = database.get_product_context(workspace_id)
        patterns = database.get_system_patterns(workspace_id)
        most_recent = None
        for p in patterns:
            p_date = getattr(p, "updated_at", None) or getattr(p, "created_at", None)
            most_recent = _most_recent_date(most_recent, p_date)
        content = {
            "product_context": (ctx.content if hasattr(ctx, "content") else {}),
            "top_patterns": [_entity_to_dict(p) for p in patterns],
        }
        return content, len(patterns) + 1, most_recent

    # ------------------------------------------------------------------
    # key_decisions  – Top 10 recent decisions
    # ------------------------------------------------------------------
    if section_id == "key_decisions":
        decisions = database.get_decisions(workspace_id, limit=10)
        most_recent = None
        for d in decisions:
            d_date = getattr(d, "updated_at", None) or getattr(d, "created_at", None)
            most_recent = _most_recent_date(most_recent, d_date)
        return [_entity_to_dict(d) for d in decisions], len(decisions), most_recent

    # ------------------------------------------------------------------
    # team_conventions  – Governance rules (Feature 1)
    # ------------------------------------------------------------------
    if section_id == "team_conventions":
        if scope_id is None:
            # Governance rules require a scope_id; skip if not provided
            return [], 0, None
        try:
            from ..governance import db_operations as gov_db_ops

            rules = gov_db_ops.get_governance_rules(workspace_id, scope_id=scope_id)
            return [_entity_to_dict(r) for r in rules], len(rules), None
        except Exception:
            return [], 0, None

    # ------------------------------------------------------------------
    # active_tasks  – In-progress & blocked progress entries
    # ------------------------------------------------------------------
    if section_id == "active_tasks":
        progress = database.get_progress(
            workspace_id, status_filter="in_progress", limit=20
        )
        all_tasks = list(progress)
        try:
            blocked = database.get_progress(
                workspace_id, status_filter="blocked", limit=10
            )
            all_tasks.extend(blocked)
        except Exception:
            pass
        most_recent = None
        for p in all_tasks:
            p_date = getattr(p, "updated_at", None) or getattr(p, "created_at", None)
            most_recent = _most_recent_date(most_recent, p_date)
        return [_entity_to_dict(p) for p in all_tasks], len(all_tasks), most_recent

    # ------------------------------------------------------------------
    # risks_and_concerns  – Custom data with category "risks"
    # ------------------------------------------------------------------
    if section_id == "risks_and_concerns":
        risks = database.get_custom_data(workspace_id, category="risks")
        return [_entity_to_dict(r) for r in risks], len(risks), None

    # ------------------------------------------------------------------
    # all_decisions  – Full decision log
    # ------------------------------------------------------------------
    if section_id == "all_decisions":
        decisions = database.get_decisions(workspace_id, limit=500)
        most_recent = None
        for d in decisions:
            d_date = getattr(d, "updated_at", None) or getattr(d, "created_at", None)
            most_recent = _most_recent_date(most_recent, d_date)
        return [_entity_to_dict(d) for d in decisions], len(decisions), most_recent

    # ------------------------------------------------------------------
    # patterns  – All system patterns
    # ------------------------------------------------------------------
    if section_id == "patterns":
        patterns = database.get_system_patterns(workspace_id)
        most_recent = None
        for p in patterns:
            p_date = getattr(p, "updated_at", None) or getattr(p, "created_at", None)
            most_recent = _most_recent_date(most_recent, p_date)
        return [_entity_to_dict(p) for p in patterns], len(patterns), most_recent

    # ------------------------------------------------------------------
    # glossary  – ProjectGlossary custom data
    # ------------------------------------------------------------------
    if section_id == "glossary":
        glossary = database.get_custom_data(workspace_id, category="ProjectGlossary")
        return [_entity_to_dict(g) for g in glossary], len(glossary), None

    # ------------------------------------------------------------------
    # knowledge_graph  – All context links
    # ------------------------------------------------------------------
    if section_id == "knowledge_graph":
        try:
            # get_context_links requires item_type and item_id; to get
            # "all" links we query the raw table instead.
            conn = database.get_db_connection(workspace_id)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, timestamp, source_item_type, source_item_id, "
                "target_item_type, target_item_id, relationship_type, "
                "description FROM context_links WHERE workspace_id = ? "
                "LIMIT 500",
                (workspace_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
            links = [dict(row) for row in rows]
            return links, len(links), None
        except Exception:
            return [], 0, None

    # ------------------------------------------------------------------
    # Unknown section – return empty
    # ------------------------------------------------------------------
    return {}, 0, None
