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

"""Functions implementing the logic for each MCP tool."""

import hashlib
import json
import logging
import re  # For markdown parsing
from datetime import datetime  # Added missing import
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import ValidationError

from ..core.exceptions import ContextPortalError, DatabaseError, DatabaseNotInitializedError, ToolArgumentError
from ..db import database as db
from ..db import models

# Lazy imports for optional dependencies (embedding service requires heavy ML stack)
# These will be imported only when actually needed
embedding_service = None
vector_store_service = None

from ..bindings import db_operations as binding_db_ops
from ..bindings import matcher as binding_matcher
from ..bindings import models as binding_models
from ..budgeting import models as budget_models
from ..budgeting.profiles import DEFAULT_WEIGHTS
from ..budgeting.scorer import score_entities
from ..budgeting.selector import estimate_context_size, select_context
from ..governance import conflict_detector
from ..governance import db_operations as gov_db_ops
from ..governance import models as gov_models
from ..onboarding import briefing as onboarding_briefing
from ..onboarding import models as onboarding_models
from ..team_sync import write_through

log = logging.getLogger(__name__)

# Track which workspaces have been seeded from config_seed.json
_seeded_workspaces: Set[str] = set()

# Built-in Engrams strategy sections (returned by get_custom_data when category='engrams_strategy')
# These are overlaid with any user customizations stored in the DB
BUILTIN_STRATEGY: Dict[str, str] = {
    "initialization": """INIT (run at session start):
  1. Determine ACTUAL_WORKSPACE_ID.
  2. List files at ACTUAL_WORKSPACE_ID/engrams/ — check for context.db.
  3. If context.db found → LOAD_EXISTING. Else → NEW_SETUP.

LOAD_EXISTING:
  Call in parallel: get_product_context, get_active_context, get_decisions(limit=5),
    get_progress(limit=5), get_system_patterns(limit=5),
    get_custom_data("critical_settings"), get_custom_data("ProjectGlossary"),
    get_custom_data("engrams_config", "default_decision_visibility"),
    get_recent_activity_summary(hours_ago=24, limit_per_type=3)
  If results non-empty → set [ENGRAMS_ACTIVE], inform user, ask what to work on.
  If DB exists but empty → set [ENGRAMS_ACTIVE], inform user DB is empty.
  If calls fail → go to INACTIVE.

NEW_SETUP:
  1. Inform user no DB found at ACTUAL_WORKSPACE_ID/engrams/context.db.
  2. Ask: "Initialize Engrams for this project?" [Yes / No]
  3. If Yes:
     a. Ask: "Is this a team project (decisions shared via git) or solo?" [Team / Solo]
     b. If Team:
        - log_custom_data(category="engrams_config", key="default_decision_visibility", value="team")
        - Inform user: "All decisions will be automatically shared via .engrams/ for git sync."
     c. If Solo:
        - log_custom_data(category="engrams_config", key="default_decision_visibility", value="individual")
        - Inform user: "Decisions will be stored locally in your Engrams database."
     d. Check workspace root for projectBrief.md.
        If found → read it, ask to import into Product Context.
        If user confirms → call update_product_context({initial_product_brief: <content>}).
        If not found → ask if user wants to define Product Context manually.
     e. Run POST_TASK_SETUP section (fetch: get_custom_data("engrams_strategy","post_task_setup")).
  4. If No → go to INACTIVE.

INACTIVE: Inform user Engrams will not be used. Status: [ENGRAMS_INACTIVE].""",

    "post_task_setup": """POST_TASK_SETUP (first-time only, after DB init):
  1. Detect project type from manifest: package.json→Node, pyproject.toml/requirements.txt/setup.py→Python,
     Cargo.toml→Rust, go.mod→Go, pom.xml/build.gradle→Java, Gemfile→Ruby, composer.json→PHP
  2. Ask user to configure post-task checks for detected type. Suggest type-appropriate commands.
  3. Let user toggle/customize checks, set severity (blocking|warning).
  4. Store → log_custom_data(category="post_task_checks", key="verification_commands",
     value={project_type, checks:[{command, name, severity, enabled}]})
  5. Record → log_decision(summary="Configured post-task verification checks for <type>",
     tags=["post-task-checks","project-setup","dx"])
  6. Proceed to LOAD_EXISTING.""",

    "governance": """GOVERNANCE CHECK (MANDATORY before any workspace mutation):
  PREFERRED: check_planned_action(workspace_id, action_description=<planned action>, tags=[<relevant tags>])
    If blocked=true → STOP, cite the conflicting decision(s), require explicit user override.
    If proceed=true → continue with the planned action.
  FALLBACK (if check_planned_action unavailable):
    Option A: get_relevant_context(task_description=<planned action>, token_budget=2000)
    Option B:
      1. Verify [ENGRAMS_ACTIVE].
      2. get_decisions(limit=20) — scan for constraints on planned task.
      3. get_scopes() — check for governance scopes.
      4. If scopes exist → get_governance_rules for each relevant scope.
      5. hard_block conflict → STOP, cite item ID+summary, require explicit override.
         soft_warn → inform user, proceed only after acknowledgment.
         No conflict → proceed.
  NOTE: Even if the pre-check is skipped, the post-write safety net will flag
  decision conflicts in the response of any write operation.""",

    "post_task": """POST_TASK (MANDATORY before attempt_completion):
  1. get_custom_data("post_task_checks","verification_commands")
     If missing → skip to step 3.
  2. Run each enabled check via execute_command.
     blocking failure → STOP, do NOT call attempt_completion. User must fix or override.
     warning failure → note and continue, include in completion summary.
  3. Categorize completed work:
     (a) Strategic decisions → log_decision (prescriptive summary, rationale, tags).
         Visibility is applied automatically by the server — do NOT set visibility unless
         the user explicitly requested a specific level.
     (b) Task completions (bugs/code/refactors/files) → log_progress(status='DONE'), NOT log_decision
     (c) New patterns → log_system_pattern
     (d) Context changes → update_active_context
  4. Log/update progress entries. Update active context if focus changed.
  5. Link related items via link_engrams_items.
  6. Call attempt_completion. Include any warning results in summary.""",

    "sync": """SYNC (trigger: "Sync Engrams" or "Engrams Sync"):
  Respond [ENGRAMS_SYNCING]. Halt current task.
  Review full chat for: new decisions, progress changes, patterns, context shifts, item relationships.
  Log: decisions(strategic only, visibility applied automatically by server),
       progress(log_progress/update_progress), patterns(log_system_pattern, visibility automatic),
       context(update_active_context/update_product_context), links(link_engrams_items),
       glossary(log_custom_data category=ProjectGlossary). Use batch_log_items for multiple same-type items.
  After: get_recent_activity_summary to confirm. Inform user sync complete. Resume or await instructions.""",

    "linking": """KNOWLEDGE GRAPH LINKING (proactive):
  Watch for relationships between discussed Engrams items (decisions, patterns, progress, custom_data).
  When spotted → propose linking: "D-5 and SP-2 seem related — link as 'implements'? [Yes/No/Custom type]"
  If confirmed → link_engrams_items(source, target, relationship_type).
  Common types: implements, clarifies, related_to, depends_on, blocks, resolves, derived_from.
  Don't be intrusive — if user declines, move on.""",

    "quality": """DECISION QUALITY:
  DECISIONS (log_decision): Strategic architectural/convention choices ONLY.
    Qualifies: patterns, tech selection, conventions, constraints, security policies, process rules.
    Does NOT qualify: bug fixes, code changes, dependency updates, refactors, file ops → use log_progress.
    Litmus test: "Would this still matter in a new session on a different feature?" Yes→decision. No→progress.
    Summary MUST be prescriptive: "Use X for Y" not "Implemented X".
      ✅ "Use SQLite FTS5 for all full-text search"  ❌ "Implemented FTS5 search"
    VISIBILITY: The server applies the workspace default automatically. Do NOT set visibility
      unless the user explicitly requests a specific level. The workspace was classified as
      team or solo during init — the server handles the rest.
  PROGRESS (log_progress): Bug fixes, code changes, task completions, implementation work.
  CONTEXT: Update active_context when focus shifts or open issues arise.
  ERRORS: log_custom_data(category='ErrorLogs', key='<timestamp>_<summary>'), update open_issues.
  SEMANTIC SEARCH: Use semantic_search_engrams for conceptual queries where keyword search falls short.
  GENERAL: NEVER run alembic or manual DB migrations. MCP server auto-creates/migrates on first tool call.
  Unified interfaces: delete_item(item_type, item_id), verify_bindings(mode='staleness'),
    get_relevant_context(dry_run=True), get_project_briefing(staleness_only=True),
    manage_budget_config, search_custom_data_value_fts(category_filter='ProjectGlossary')""",
}


def _ensure_embedding_service():
    """Lazy-load embedding service when needed."""
    global embedding_service, vector_store_service
    if embedding_service is None:
        try:
            from ..core import embedding_service as _es
            from ..db import vector_store_service as _vss

            embedding_service = _es
            vector_store_service = _vss
        except ImportError as e:
            log.warning(f"Embedding service not available: {e}")
            raise ToolArgumentError(
                "Semantic search requires sentence-transformers and dependencies to be installed"
            )


# --- Governance Integration Helper ---


def _apply_governance_checks(
    workspace_id: str,
    item_type: str,
    item_id: Optional[int],
    item_data: Dict[str, Any],
    scope_id: Optional[int],
    visibility: Optional[str],
    response: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply governance scope assignment and conflict detection after logging an item.

    This is a non-fatal enhancement — errors are caught and logged as warnings,
    never failing the primary log operation.

    Args:
        workspace_id: The workspace identifier.
        item_type: Entity type ('decision', 'system_pattern', etc.).
        item_id: The ID of the newly logged item (None if not yet assigned).
        item_data: The item's data dict (for conflict detection).
        scope_id: Optional governance scope ID to assign.
        visibility: Optional visibility level.
        response: The response dict to augment with governance info.

    Returns:
        The response dict, potentially augmented with governance_warnings and override_status.
    """
    # Always run decision-conflict checks (no scope required)
    try:
        decision_conflicts = conflict_detector.check_decision_conflicts(
            workspace_id, item_type, item_data
        )
        if decision_conflicts.has_conflict:
            response.setdefault("decision_warnings", []).extend(
                [c if isinstance(c, str) else c for c in decision_conflicts.conflicts]
            )
            if decision_conflicts.warnings:
                response.setdefault("decision_warnings", []).extend(
                    decision_conflicts.warnings
                )
            response["decision_conflict_detected"] = True
    except Exception as dec_err:
        log.warning("Decision conflict check failed (non-fatal): %s", dec_err)

    if scope_id is None or item_id is None:
        return response

    try:
        conn = db.get_db_connection(workspace_id)
        cursor = conn.cursor()

        # Map item_type to table name
        table_map = {
            "decision": "decisions",
            "system_pattern": "system_patterns",
            "progress_entry": "progress_entries",
            "custom_data": "custom_data",
        }
        table = table_map.get(item_type)
        if not table:
            log.warning(
                "Governance: unknown item_type '%s', skipping scope assignment",
                item_type,
            )
            return response

        # Update scope_id and visibility on the item
        vis = visibility or "workspace"
        cursor.execute(
            f"UPDATE {table} SET scope_id = ?, visibility = ?, override_status = 'pending_review' WHERE id = ?",
            (scope_id, vis, item_id),
        )
        conn.commit()
        cursor.close()

        # Check for conflicts with team rules
        scope = gov_db_ops.get_scope_by_id(workspace_id, scope_id)
        if scope and scope.scope_type == "individual" and scope.parent_scope_id:
            # This is an individual scope with a team parent — run conflict detection
            conflicts = conflict_detector.check_conflicts(
                workspace_id, item_type, item_data, scope_id=scope_id
            )
            if conflicts and conflicts.has_conflict:
                response["governance_warnings"] = [
                    c if isinstance(c, str) else c for c in conflicts.conflicts
                ]
                response["governance_action"] = conflicts.action
                response["override_status"] = "conflict_detected"
                if conflicts.warnings:
                    response.setdefault("governance_warnings", []).extend(
                        conflicts.warnings
                    )

                # Update override_status in DB
                try:
                    gov_db_ops.update_item_override_status(
                        workspace_id,
                        item_type,
                        item_id,
                        override_status="conflict_detected",
                    )
                except Exception as status_err:
                    log.warning(
                        "Governance: failed to update override_status: %s", status_err
                    )
            else:
                # No conflict — mark as compliant
                try:
                    gov_db_ops.update_item_override_status(
                        workspace_id, item_type, item_id, override_status="compliant"
                    )
                except Exception as status_err:
                    log.warning(
                        "Governance: failed to update override_status: %s", status_err
                    )

        response["scope_id"] = scope_id
        response["visibility"] = vis

    except Exception as gov_err:
        log.warning("Governance check failed (non-fatal): %s", gov_err)

    return response


def _seed_config_from_file(workspace_id: str) -> None:
    """
    On first use, seeds engrams_config from .engrams/config_seed.json
    if the config doesn't already exist in the DB.
    """
    try:
        existing = db.get_custom_data(
            workspace_id,
            category="engrams_config",
            key="default_decision_visibility",
        )
        if existing and len(existing) > 0:
            return  # Already seeded
    except Exception:
        pass  # DB might not exist yet, that's fine

    # Look for seed file
    seed_path = Path(workspace_id) / ".engrams" / "config_seed.json"
    if not seed_path.exists():
        return

    try:
        with open(seed_path, "r") as f:
            seed_data = json.load(f)
        visibility = seed_data.get("default_decision_visibility")
        if visibility in ("team", "individual", "proposed", "workspace"):
            data_to_log = models.CustomData(
                category="engrams_config",
                key="default_decision_visibility",
                value=visibility,
                visibility=None,
            )
            db.log_custom_data(workspace_id, data_to_log)
            log.info(
                "Seeded default_decision_visibility=%s from config_seed.json",
                visibility,
            )
    except Exception as e:
        log.warning("Failed to seed config from config_seed.json: %s", e)


def _resolve_effective_visibility(workspace_id: str, explicit_visibility: Optional[str]) -> Optional[str]:
    """
    Resolves effective visibility for an item.

    If the caller explicitly set visibility, use that. Otherwise, check
    for a workspace-level default stored in custom_data under
    category='engrams_config', key='default_decision_visibility'.

    Falls back to 'individual' if no configuration is found (safe default
    that never accidentally shares).
    """
    if explicit_visibility is not None:
        return explicit_visibility

    # Seed config from file on first access per workspace
    if workspace_id not in _seeded_workspaces:
        _seed_config_from_file(workspace_id)
        _seeded_workspaces.add(workspace_id)

    try:
        defaults = db.get_custom_data(
            workspace_id,
            category="engrams_config",
            key="default_decision_visibility",
        )
        if defaults and len(defaults) > 0:
            value = defaults[0].value
            if value in ("team", "individual", "proposed", "workspace"):
                return value
    except Exception as e:
        log.warning("Failed to read default_decision_visibility config: %s", e)

    return "individual"  # Safe fallback — never accidentally shared


def _augment_with_auto_create_notice(workspace_id: str, response: Any) -> Any:
    """
    If the database for this workspace was auto-created (not via ``engrams init``),
    augments the response with a notice so the LLM can inform the user.

    The notice is only included once per workspace — after the first response
    includes it, the flag is cleared.

    Works with both dict responses and list responses (wraps list in a dict
    with the notice).
    """
    if not db.was_auto_created(workspace_id):
        return response

    notice = {
        "_engrams_auto_initialized": True,
        "_notice": (
            "The Engrams database was auto-created because it did not exist. "
            "For full setup (team sync, .engrams/ directory structure), "
            "run 'engrams init --tool <name>' in your project terminal."
        ),
    }

    # Clear the flag so the notice only appears once
    db.clear_auto_created_flag(workspace_id)

    if isinstance(response, dict):
        return {**notice, **response}
    elif isinstance(response, list):
        return {"_engrams_auto_initialized": True, "_notice": notice["_notice"], "results": response}
    else:
        return response


# --- Tool Handler Functions ---


# --- FTS Query Utilities (handler layer) ---
def _prepare_fts_query(
    query: str,
    allowed_columns: Optional[List[str]] = None,
    default_column: Optional[str] = None,
) -> str:
    """Normalize user-provided FTS MATCH queries to avoid parser errors without touching DB layer.

    - If the query contains a colon but not with a known column prefix, treat it as a literal.
    - If it contains characters like '.' or '"' that cause parse errors, treat as a literal.
    - When default_column is provided, prefix the literal with that column.
    """
    if query is None:
        return ""
    q = query.strip()
    if not q:
        return q

    has_known_prefix = False
    if allowed_columns:
        for c in allowed_columns:
            if f"{c}:" in q:
                has_known_prefix = True
                break

    def as_literal(text: str) -> str:
        esc = text.replace('"', '""')
        if default_column:
            return f'{default_column}:"{esc}"'
        return f'"{esc}"'

    # If colon is present but not using a known prefix, treat entire query as literal
    if ":" in q and not has_known_prefix:
        return as_literal(q)

    # If special characters that commonly break the parser are present, quote as literal
    if any(ch in q for ch in [".", "/", "\\", '"']) and not has_known_prefix:
        return as_literal(q)

    return q


def handle_get_product_context(args: models.GetContextArgs) -> Dict[str, Any]:
    """
    Handles the 'get_product_context' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    """
    try:
        context_model = db.get_product_context(args.workspace_id)
        result = context_model.content
        return _augment_with_auto_create_notice(args.workspace_id, result)
    except DatabaseNotInitializedError:
        raise  # Let it propagate with its clear message
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting product context: {e}")
    except Exception as e:
        # Log the full error for debugging if it's truly unexpected
        log.exception(
            f"Unexpected error in get_product_context for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_product_context: {e}")


def handle_update_product_context(args: models.UpdateContextArgs) -> Dict[str, Any]:
    """
    Handles the 'update_product_context' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a success message dictionary.
    """
    try:
        # The Pydantic model 'args' (UpdateContextArgs) now handles validation
        # for 'content' vs 'patch_content'.
        # The database function 'db.update_product_context' now expects UpdateContextArgs.
        db.update_product_context(args.workspace_id, args)
        # FastMCP expects direct results. A status message is a reasonable result.
        return {"status": "success", "message": "Product context updated successfully."}
    except (
        ValidationError
    ) as e:  # Should not happen if FastMCP validates schema, but good for direct calls
        raise ToolArgumentError(f"Invalid content structure: {e}")
    except DatabaseError as e:
        raise ContextPortalError(f"Database error updating product context: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in update_product_context for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in update_product_context: {e}")


def handle_log_decision(args: models.LogDecisionArgs) -> Dict[str, Any]:
    """
    Handles the 'log_decision' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns the logged decision as a dictionary.
    """
    try:
        # Resolve effective visibility from workspace config if not explicitly set
        effective_visibility = _resolve_effective_visibility(args.workspace_id, args.visibility)

        decision_to_log = models.Decision(
            summary=args.summary,
            rationale=args.rationale,
            implementation_details=args.implementation_details,
            tags=args.tags,
            visibility=effective_visibility,
            uuid=args.uuid if hasattr(args, "uuid") else None,
            # Timestamp is added automatically by the Pydantic model's default_factory
        )
        logged_decision = db.log_decision(args.workspace_id, decision_to_log)

        # --- Add to Vector Store ---
        if logged_decision and logged_decision.id is not None:
            try:
                _ensure_embedding_service()
                text_to_embed = f"Decision Summary: {logged_decision.summary}\n"
                if logged_decision.rationale:
                    text_to_embed += f"Rationale: {logged_decision.rationale}\n"
                if logged_decision.implementation_details:
                    text_to_embed += f"Implementation Details: {logged_decision.implementation_details}"

                vector = embedding_service.get_embedding(text_to_embed.strip())

                metadata_for_vector = {
                    "engrams_item_id": str(logged_decision.id),
                    "engrams_item_type": "decision",
                    "summary": logged_decision.summary,
                    "timestamp_created": logged_decision.timestamp.isoformat(),
                    "tags": (
                        ", ".join(logged_decision.tags)
                        if logged_decision.tags
                        else None
                    ),
                }
                vector_store_service.upsert_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="decision",
                    item_id=str(logged_decision.id),
                    vector=vector,
                    metadata=metadata_for_vector,
                )
                log.info(
                    f"Successfully generated and stored embedding for decision ID {logged_decision.id}"
                )
            except Exception as e_embed:
                log.error(
                    f"Failed to generate/store embedding for decision ID {logged_decision.id}: {e_embed}",
                    exc_info=True,
                )
        # --- End Add to Vector Store ---

        response = logged_decision.model_dump(mode="json")
        # Filesystem-first: .engrams/ is the authoritative source for team items.
        # This write MUST succeed — failure means the operation fails.
        if getattr(logged_decision, "visibility", None) == "team":
            write_through.write_decision_file(args.workspace_id, logged_decision, [])
        return _apply_governance_checks(
            workspace_id=args.workspace_id,
            item_type="decision",
            item_id=logged_decision.id,
            item_data=response,
            scope_id=args.scope_id,
            visibility=effective_visibility,
            response=response,
        )
    except DatabaseError as e:
        raise ContextPortalError(f"Database error logging decision: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in log_decision for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in log_decision: {e}")


# --- Added handlers --- # This comment might be outdated, these are just more handlers


def handle_get_decisions(args: models.GetDecisionsArgs) -> List[Dict[str, Any]]:
    """
    Handles the 'get_decisions' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of decision dictionaries.
    """
    try:
        decisions_list = db.get_decisions(
            args.workspace_id,
            limit=args.limit,
            tags_filter_include_all=args.tags_filter_include_all,
            tags_filter_include_any=args.tags_filter_include_any,
        )
        return [d.model_dump(mode="json") for d in decisions_list]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting decisions: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_decisions for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_decisions: {e}")


def handle_search_decisions_fts(
    args: models.SearchDecisionsArgs,
) -> List[Dict[str, Any]]:
    """
    Handles the 'search_decisions_fts' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of decision dictionaries.
    """
    try:
        safe_query = _prepare_fts_query(
            args.query_term,
            allowed_columns=["summary", "rationale", "implementation_details", "tags"],
            default_column="summary",
        )
        decisions_list = db.search_decisions_fts(
            args.workspace_id, query_term=safe_query, limit=args.limit
        )
        return [d.model_dump(mode="json") for d in decisions_list]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error searching decisions: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in search_decisions_fts for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in search_decisions_fts: {e}")


def handle_get_active_context(args: models.GetContextArgs) -> Dict[str, Any]:
    """
    Handles the 'get_active_context' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    """
    try:
        context_model = db.get_active_context(args.workspace_id)
        result = context_model.content
        return _augment_with_auto_create_notice(args.workspace_id, result)
    except DatabaseNotInitializedError:
        raise  # Let it propagate with its clear message
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting active context: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_active_context for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_active_context: {e}")


def handle_update_active_context(args: models.UpdateContextArgs) -> Dict[str, Any]:
    """
    Handles the 'update_active_context' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a success message dictionary.
    """
    try:
        # The Pydantic model 'args' (UpdateContextArgs) now handles validation
        # for 'content' vs 'patch_content'.
        # The database function 'db.update_active_context' now expects UpdateContextArgs.
        db.update_active_context(args.workspace_id, args)
        return {"status": "success", "message": "Active context updated successfully."}
    except ValidationError as e:  # Should not happen if FastMCP validates
        raise ToolArgumentError(f"Invalid content structure: {e}")
    except DatabaseError as e:
        raise ContextPortalError(f"Database error updating active context: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in update_active_context for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in update_active_context: {e}")


def handle_log_progress(args: models.LogProgressArgs) -> Dict[str, Any]:
    """
    Handles the 'log_progress' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns the logged progress entry as a dictionary.
    """
    try:
        progress_to_log = models.ProgressEntry(
            status=args.status,
            description=args.description,
            parent_id=args.parent_id,
            # linked_item_type and linked_item_id are not part of ProgressEntry model itself
        )
        logged_progress = db.log_progress(args.workspace_id, progress_to_log)

        # If linking information is provided, create the link
        if (
            args.linked_item_type
            and args.linked_item_id
            and logged_progress.id is not None
        ):
            try:
                link_to_create = models.ContextLink(
                    source_item_type="progress_entry",  # The progress entry is the source
                    source_item_id=str(
                        logged_progress.id
                    ),  # ID of the newly created progress entry
                    target_item_type=args.linked_item_type,
                    target_item_id=args.linked_item_id,
                    relationship_type=args.link_relationship_type,  # Use the relationship type from args
                    description=f"Progress entry '{logged_progress.description[:30]}...' automatically linked.",
                )
                db.log_context_link(args.workspace_id, link_to_create)
                log.info(
                    f"Automatically linked progress entry ID {logged_progress.id} to {args.linked_item_type} ID {args.linked_item_id}"
                )
            except Exception as link_e:
                # Log the linking error but don't let it fail the whole progress logging
                log.error(
                    f"Failed to automatically link progress entry ID {logged_progress.id} for workspace {args.workspace_id}: {link_e}"
                )
                # Optionally, add this error to the response if the MCP tool schema supports it

        # --- Add to Vector Store ---
        if logged_progress and logged_progress.id is not None:
            try:
                _ensure_embedding_service()
                text_to_embed = f"Progress: {logged_progress.status} - {logged_progress.description}"

                vector = embedding_service.get_embedding(text_to_embed.strip())

                metadata_for_vector = {
                    "engrams_item_id": str(logged_progress.id),
                    "engrams_item_type": "progress_entry",
                    "status": logged_progress.status,
                    "description_snippet": logged_progress.description[
                        :100
                    ],  # Snippet for quick view
                    "timestamp_created": logged_progress.timestamp.isoformat(),
                    "parent_id": (
                        str(logged_progress.parent_id)
                        if logged_progress.parent_id
                        else None
                    ),
                }
                vector_store_service.upsert_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="progress_entry",
                    item_id=str(logged_progress.id),
                    vector=vector,
                    metadata=metadata_for_vector,
                )
                log.info(
                    f"Successfully generated and stored embedding for progress entry ID {logged_progress.id}"
                )
            except Exception as e_embed:
                log.error(
                    f"Failed to generate/store embedding for progress entry ID {logged_progress.id}: {e_embed}",
                    exc_info=True,
                )
        # --- End Add to Vector Store ---

        response = logged_progress.model_dump(mode="json")
        return _apply_governance_checks(
            workspace_id=args.workspace_id,
            item_type="progress_entry",
            item_id=logged_progress.id,
            item_data=response,
            scope_id=args.scope_id,
            visibility=args.visibility,
            response=response,
        )
    except DatabaseError as e:
        raise ContextPortalError(f"Database error logging progress: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in log_progress for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in log_progress: {e}")


def handle_get_progress(args: models.GetProgressArgs) -> List[Dict[str, Any]]:
    """
    Handles the 'get_progress' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of progress entry dictionaries.
    """
    try:
        progress_list = db.get_progress(
            args.workspace_id,
            status_filter=args.status_filter,
            parent_id_filter=args.parent_id_filter,
            limit=args.limit,
        )
        return [p.model_dump(mode="json") for p in progress_list]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting progress: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_progress for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_progress: {e}")


def handle_update_progress(args: models.UpdateProgressArgs) -> Dict[str, Any]:
    """
    Handles the 'update_progress' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a status message dictionary.
    """
    try:
        updated = db.update_progress_entry(args.workspace_id, args)

        if updated:
            # --- Update Vector Store ---
            # Re-embedding on update requires fetching the full, updated entry from the DB
            # to get the complete description and status for the vector.
            # This requires a db.get_progress_entry_by_id function, which is not yet implemented.
            # For now, we will skip re-embedding on update and log a warning.
            # A future enhancement would be to implement db.get_progress_entry_by_id
            # and then call vector_store_service.upsert_item_embedding here.
            log.warning(
                f"Vector store update skipped for progress entry ID {args.progress_id} on update. Requires db.get_progress_entry_by_id for accurate re-embedding."
            )
            # --- End Update Vector Store ---

            return {
                "status": "success",
                "message": f"Progress entry ID {args.progress_id} updated successfully.",
            }
        else:
            return {
                "status": "success",
                "message": f"Progress entry ID {args.progress_id} not found for update.",
            }
    except ValueError as e:  # Catch validation errors from the handler/db call
        raise ToolArgumentError(str(e))
    except DatabaseError as e:
        raise ContextPortalError(
            f"Database error updating progress entry ID {args.progress_id}: {e}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in handle_update_progress for workspace {args.workspace_id}, ID {args.progress_id}"
        )
        raise ContextPortalError(f"Unexpected error updating progress entry: {e}")


def handle_delete_progress_by_id(args: models.DeleteProgressByIdArgs) -> Dict[str, Any]:
    """
    Handles the 'delete_progress_by_id' MCP tool.
    Deletes a progress entry by its ID.
    """
    try:
        deleted_from_db = db.delete_progress_entry_by_id(
            args.workspace_id, args.progress_id
        )

        if deleted_from_db:
            try:
                # --- Delete from Vector Store ---
                vector_store_service.delete_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="progress_entry",
                    item_id=str(args.progress_id),
                )
                log.info(
                    f"Successfully deleted embedding for progress entry ID {args.progress_id}"
                )
                # --- End Delete from Vector Store ---
                return {
                    "status": "success",
                    "message": f"Progress entry ID {args.progress_id} and its embedding deleted successfully.",
                }
            except Exception as e_vec_del:
                log.error(
                    f"Failed to delete embedding for progress entry ID {args.progress_id} (DB record was deleted): {e_vec_del}",
                    exc_info=True,
                )
                # Return success for DB deletion but acknowledge embedding deletion failure.
                return {
                    "status": "partial_success",
                    "message": f"Progress entry ID {args.progress_id} deleted from database, but failed to delete its embedding: {e_vec_del}",
                }
        else:
            # This case means the ID was valid (e.g. integer) but not found in DB.
            # No need to attempt vector deletion if not found in DB.
            return {
                "status": "success",
                "message": f"Progress entry ID {args.progress_id} not found in database.",
            }
    except DatabaseError as e:
        raise ContextPortalError(
            f"Database error deleting progress entry ID {args.progress_id}: {e}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in handle_delete_progress_by_id for workspace {args.workspace_id}, ID {args.progress_id}"
        )
        raise ContextPortalError(f"Unexpected error deleting progress entry: {e}")


def handle_log_system_pattern(args: models.LogSystemPatternArgs) -> Dict[str, Any]:
    """
    Handles the 'log_system_pattern' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns the logged system pattern as a dictionary.
    """
    try:
        # Resolve effective visibility from workspace config if not explicitly set
        effective_visibility = _resolve_effective_visibility(args.workspace_id, args.visibility)

        pattern_to_log = models.SystemPattern(
            name=args.name, description=args.description, tags=args.tags,
            visibility=effective_visibility,
        )
        logged_pattern = db.log_system_pattern(args.workspace_id, pattern_to_log)

        # --- Add to Vector Store ---
        if logged_pattern and logged_pattern.id is not None:
            try:
                text_to_embed = f"System Pattern: {logged_pattern.name}\nDescription: {logged_pattern.description if logged_pattern.description else ''}"

                vector = embedding_service.get_embedding(text_to_embed.strip())

                metadata_for_vector = {
                    "engrams_item_id": str(logged_pattern.id),
                    "engrams_item_type": "system_pattern",
                    "name": logged_pattern.name,
                    "timestamp_created": logged_pattern.timestamp.isoformat(),  # Assuming SystemPattern has a timestamp
                    "tags": (
                        ", ".join(logged_pattern.tags) if logged_pattern.tags else None
                    ),
                }
                vector_store_service.upsert_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="system_pattern",
                    item_id=str(logged_pattern.id),
                    vector=vector,
                    metadata=metadata_for_vector,
                )
                log.info(
                    f"Successfully generated and stored embedding for system pattern ID {logged_pattern.id}"
                )
            except Exception as e_embed:
                log.error(
                    f"Failed to generate/store embedding for system pattern ID {logged_pattern.id}: {e_embed}",
                    exc_info=True,
                )
        # --- End Add to Vector Store ---

        response = logged_pattern.model_dump(mode="json")
        # Filesystem-first: .engrams/ is the authoritative source for team items.
        # This write MUST succeed — failure means the operation fails.
        if getattr(logged_pattern, "visibility", None) == "team":
            write_through.write_pattern_file(args.workspace_id, logged_pattern, [])
        return _apply_governance_checks(
            workspace_id=args.workspace_id,
            item_type="system_pattern",
            item_id=logged_pattern.id,
            item_data=response,
            scope_id=args.scope_id,
            visibility=effective_visibility,
            response=response,
        )
    except DatabaseError as e:
        raise ContextPortalError(f"Database error logging system pattern: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in log_system_pattern for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in log_system_pattern: {e}")


def handle_get_system_patterns(
    args: models.GetSystemPatternsArgs,
) -> List[Dict[str, Any]]:
    """
    Handles the 'get_system_patterns' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of system pattern dictionaries.
    """
    try:
        patterns_list = db.get_system_patterns(
            args.workspace_id,
            tags_filter_include_all=args.tags_filter_include_all,
            tags_filter_include_any=args.tags_filter_include_any,
        )
        return [p.model_dump(mode="json") for p in patterns_list]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting system patterns: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_system_patterns for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_system_patterns: {e}")


def handle_get_engrams_schema(
    args: models.GetEngramsSchemaArgs,
) -> Dict[str, Dict[str, Any]]:
    """
    Handles the 'get_engrams_schema' MCP tool.
    Retrieves the JSON schema for all registered Engrams tools.
    Assumes 'args' is an already validated Pydantic model instance.
    """
    try:
        log.info(f"Handling get_engrams_schema for workspace {args.workspace_id}")
        tool_schemas: Dict[str, Dict[str, Any]] = {}
        for tool_name, model_class in models.TOOL_ARG_MODELS.items():
            # Ensure model_class is a Pydantic BaseModel before calling model_json_schema
            if hasattr(model_class, "model_json_schema") and callable(
                model_class.model_json_schema
            ):
                tool_schemas[tool_name] = model_class.model_json_schema()
            else:
                # This case should ideally not happen if TOOL_ARG_MODELS is correctly populated
                log.warning(
                    f"Model class for tool '{tool_name}' is not a Pydantic model or does not have 'model_json_schema' method."
                )
                tool_schemas[tool_name] = {"error": "Schema not available"}

        return tool_schemas
    except Exception as e:
        log.exception(
            f"Unexpected error in get_engrams_schema for workspace {args.workspace_id}"
        )
        # Return a more structured error if possible, or a generic one
        raise ContextPortalError(f"Unexpected error retrieving Engrams schema: {e}")


def handle_get_recent_activity_summary(
    args: models.GetRecentActivitySummaryArgs,
) -> Dict[str, Any]:
    """
    Handles the 'get_recent_activity_summary' MCP tool.
    Retrieves a summary of recent activity from the database.
    """
    try:
        log.info(
            f"Handling get_recent_activity_summary for workspace {args.workspace_id} with args: {args.model_dump_json()}"
        )
        summary_data = db.get_recent_activity_summary_data(
            workspace_id=args.workspace_id,
            hours_ago=args.hours_ago,
            since_timestamp=args.since_timestamp,
            limit_per_type=(
                args.limit_per_type if args.limit_per_type is not None else 5
            ),  # Ensure default if None
        )
        return _augment_with_auto_create_notice(args.workspace_id, summary_data)
    except DatabaseError as e:
        log.error(
            f"Database error in get_recent_activity_summary for workspace {args.workspace_id}: {e}"
        )
        raise ContextPortalError(f"Database error retrieving recent activity: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_recent_activity_summary for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error retrieving recent activity: {e}")


def handle_log_custom_data(args: models.LogCustomDataArgs) -> Dict[str, Any]:
    """
    Handles the 'log_custom_data' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns the logged custom data entry as a dictionary.
    """
    try:
        # Don't override visibility for system-internal categories
        SYSTEM_CATEGORIES = {"engrams_config", "engrams_strategy", "post_task_checks"}
        if args.category in SYSTEM_CATEGORIES:
            effective_visibility = args.visibility
        else:
            effective_visibility = _resolve_effective_visibility(args.workspace_id, args.visibility)

        data_to_log = models.CustomData(
            category=args.category, key=args.key, value=args.value,
            visibility=effective_visibility,
        )
        # Assuming CustomData model has a metadata field, or we add it if needed for cache_hint
        # For now, the LogCustomDataArgs does not have metadata.
        # If it did: data_to_log = models.CustomData(category=args.category, key=args.key, value=args.value, metadata=args.metadata)

        logged_data = db.log_custom_data(args.workspace_id, data_to_log)

        # --- Add to Vector Store ---
        if logged_data and logged_data.id is not None:
            # Only embed if value is string-like or can be reasonably converted to text
            text_to_embed = None
            if isinstance(logged_data.value, str):
                text_to_embed = logged_data.value
            elif isinstance(logged_data.value, (dict, list)):
                try:
                    # Simple JSON string representation for dict/list
                    text_to_embed = json.dumps(logged_data.value)
                except TypeError:
                    log.warning(
                        f"Custom data value for {logged_data.category}/{logged_data.key} is not JSON serializable for embedding."
                    )

            if text_to_embed:
                # Add category and key to text for better contextual embedding
                contextual_text_to_embed = f"Category: {logged_data.category}\nKey: {logged_data.key}\nValue: {text_to_embed}"
                try:
                    _ensure_embedding_service()
                    vector = embedding_service.get_embedding(
                        contextual_text_to_embed.strip()
                    )

                    metadata_for_vector = {
                        "engrams_item_id": str(logged_data.id),
                        "engrams_item_type": "custom_data",
                        "category": logged_data.category,
                        "key": logged_data.key,
                        "timestamp_created": logged_data.timestamp.isoformat(),
                        # "value_type": str(type(logged_data.value).__name__) # Could be useful metadata
                    }
                    # Add metadata from CustomData if it exists and is simple
                    if hasattr(logged_data, "metadata") and isinstance(
                        logged_data.metadata, dict
                    ):
                        for k, v in logged_data.metadata.items():
                            if isinstance(
                                v, (str, int, float, bool)
                            ):  # Only simple types for Chroma metadata
                                metadata_for_vector[f"custom_meta_{k}"] = v

                    vector_store_service.upsert_item_embedding(
                        workspace_id=args.workspace_id,
                        item_type="custom_data",
                        item_id=str(
                            logged_data.id
                        ),  # Using internal DB ID as part of Chroma ID
                        vector=vector,
                        metadata=metadata_for_vector,
                    )
                    log.info(
                        f"Successfully generated and stored embedding for custom_data ID {logged_data.id} ({logged_data.category}/{logged_data.key})"
                    )
                except Exception as e_embed:
                    log.error(
                        f"Failed to generate/store embedding for custom_data ID {logged_data.id} ({logged_data.category}/{logged_data.key}): {e_embed}",
                        exc_info=True,
                    )
            else:
                log.debug(
                    f"Skipping embedding for custom_data ID {logged_data.id} ({logged_data.category}/{logged_data.key}) as value is not text-like."
                )
        # --- End Add to Vector Store ---

        response = logged_data.model_dump(mode="json")
        # Filesystem-first: .engrams/ is the authoritative source for team items.
        # This write MUST succeed — failure means the operation fails.
        if getattr(logged_data, "visibility", None) == "team":
            all_entries = db.get_custom_data(
                args.workspace_id,
                category=args.category,
                visibility_filter="team",
            )
            write_through.write_shared_data_file(
                args.workspace_id, args.category, all_entries
            )
        return _apply_governance_checks(
            workspace_id=args.workspace_id,
            item_type="custom_data",
            item_id=logged_data.id,
            item_data=response,
            scope_id=args.scope_id,
            visibility=effective_visibility,
            response=response,
        )
    except DatabaseError as e:
        raise ContextPortalError(f"Database error logging custom data: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in log_custom_data for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in log_custom_data: {e}")


def handle_get_custom_data(args: models.GetCustomDataArgs) -> List[Dict[str, Any]]:
    """
    Handles the 'get_custom_data' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of custom data entry dictionaries.

    Special behavior: category='engrams_strategy' returns built-in strategy sections
    (from BUILTIN_STRATEGY), overlaid with any user customizations stored in the DB.
    """
    try:
        # Special handling for built-in engrams_strategy sections
        if args.category == "engrams_strategy":
            # Fetch any user customizations from DB
            db_entries = db.get_custom_data(
                args.workspace_id, category="engrams_strategy", key=args.key
            )
            db_by_key = {e.key: e.model_dump(mode="json") for e in db_entries}

            if args.key is not None:
                # Specific key requested
                if args.key in db_by_key:
                    # User override takes precedence
                    return [db_by_key[args.key]]
                elif args.key in BUILTIN_STRATEGY:
                    # Return built-in section as a synthetic result
                    return [{
                        "id": None,
                        "category": "engrams_strategy",
                        "key": args.key,
                        "value": BUILTIN_STRATEGY[args.key],
                        "created_at": None,
                        "source": "builtin",
                    }]
                else:
                    return []
            else:
                # Return all: built-ins merged with DB overrides
                result = []
                seen_keys = set()
                # DB entries first (they override built-ins)
                for key, entry in db_by_key.items():
                    result.append(entry)
                    seen_keys.add(key)
                # Add remaining built-ins not overridden
                for key, value in BUILTIN_STRATEGY.items():
                    if key not in seen_keys:
                        result.append({
                            "id": None,
                            "category": "engrams_strategy",
                            "key": key,
                            "value": value,
                            "created_at": None,
                            "source": "builtin",
                        })
                return result

        # Standard behavior for all other categories
        data_list = db.get_custom_data(
            args.workspace_id, category=args.category, key=args.key
        )
        return [d.model_dump(mode="json") for d in data_list]
    except ValueError as e:  # From db function if key w/o category, or other validation
        raise ToolArgumentError(str(e))  # Pass specific error message
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting custom data: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_custom_data for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in get_custom_data: {e}")


def handle_delete_custom_data(args: models.DeleteCustomDataArgs) -> Dict[str, Any]:
    """
    Handles the 'delete_custom_data' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a status message dictionary.
    """
    try:
        deleted = db.delete_custom_data(
            args.workspace_id, category=args.category, key=args.key
        )
        if deleted:
            return {
                "status": "success",
                "message": f"Custom data '{args.category}/{args.key}' deleted.",
            }
        else:
            return {
                "status": "success",
                "message": f"Custom data '{args.category}/{args.key}' not found for deletion.",
            }
    except DatabaseError as e:
        raise ContextPortalError(f"Database error deleting custom data: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in delete_custom_data for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error in delete_custom_data: {e}")


def handle_search_project_glossary_fts(
    args: models.SearchProjectGlossaryArgs,
) -> List[Dict[str, Any]]:
    """
    Handles the 'search_project_glossary_fts' MCP tool.
    Assumes 'args' is an already validated Pydantic model instance.
    Returns a list of glossary entry dictionaries.
    """
    try:
        safe_query = _prepare_fts_query(
            args.query_term,
            allowed_columns=["category", "key", "value_text"],
            default_column="value_text",
        )
        glossary_entries = db.search_project_glossary_fts(
            args.workspace_id, query_term=safe_query, limit=args.limit
        )
        return [entry.model_dump(mode="json") for entry in glossary_entries]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error searching project glossary: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in search_project_glossary_fts for workspace {args.workspace_id}"
        )
        raise ContextPortalError(
            f"Unexpected error in search_project_glossary_fts: {e}"
        )


def handle_search_custom_data_value_fts(
    args: models.SearchCustomDataValueArgs,
) -> List[Dict[str, Any]]:
    """
    Handles the 'search_custom_data_value_fts' MCP tool.
    Searches custom data entries using FTS, optionally filtered by category.
    """
    try:
        safe_query = _prepare_fts_query(
            args.query_term,
            allowed_columns=["category", "key", "value_text"],
            default_column="value_text",
        )
        results = db.search_custom_data_value_fts(
            args.workspace_id,
            query_term=safe_query,
            category_filter=args.category_filter,
            limit=args.limit,
        )
        return [item.model_dump(mode="json") for item in results]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error searching custom data values: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in search_custom_data_value_fts for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error searching custom data values: {e}")


# --- Semantic Search Handler ---


async def handle_semantic_search_engrams(
    args: models.SemanticSearchEngramsArgs,
) -> List[Dict[str, Any]]:
    """
    Handles the 'semantic_search_engrams' MCP tool.
    Performs a semantic search using embeddings and vector store, with optional metadata filters.
    """
    try:
        log.info(
            f"Handling semantic_search_engrams for workspace {args.workspace_id} with query: '{args.query_text[:50]}...'"
        )

        query_vector = embedding_service.get_embedding(args.query_text)

        # Construct ChromaDB filters
        chroma_filters = {}
        and_conditions = []

        if args.filter_item_types:
            and_conditions.append(
                {"engrams_item_type": {"$in": args.filter_item_types}}
            )

        if args.filter_tags_include_all:
            # For $all behavior with $contains, we need an $and for each tag
            tag_all_conditions = [
                {"tags": {"$contains": tag}} for tag in args.filter_tags_include_all
            ]
            if tag_all_conditions:
                and_conditions.append({"$and": tag_all_conditions})

        if args.filter_tags_include_any:
            # For $or behavior with $contains
            tag_any_conditions = [
                {"tags": {"$contains": tag}} for tag in args.filter_tags_include_any
            ]
            if tag_any_conditions:
                and_conditions.append({"$or": tag_any_conditions})

        if args.filter_custom_data_categories:
            # This filter is only meaningful if 'custom_data' is in item_types or no item_types are specified
            category_condition = {
                "category": {"$in": args.filter_custom_data_categories}
            }
            if args.filter_item_types and "custom_data" in args.filter_item_types:
                and_conditions.append(category_condition)
            elif (
                not args.filter_item_types
            ):  # If no item_type filter, apply category filter broadly (might hit non-custom_data items if they had 'category' metadata)
                and_conditions.append(category_condition)

        if and_conditions:
            if len(and_conditions) == 1:
                chroma_filters = and_conditions[0]
            else:
                chroma_filters = {"$and": and_conditions}

        log.debug(f"ChromaDB query filters: {chroma_filters}")

        search_results = vector_store_service.query_vector_store(
            workspace_id=args.workspace_id,
            query_vector=query_vector,
            top_k=args.top_k,
            filters=chroma_filters if chroma_filters else None,
        )

        # Process results: search_results is List[Dict] with 'chroma_doc_id', 'distance', 'metadata'
        # We need to potentially fetch full items from SQLite based on metadata.engrams_item_id and engrams_item_type
        # For now, just return the direct results from vector store, which includes metadata.
        # A more advanced version would re-hydrate with full SQLite objects.

        # Example of enriching results (conceptual, actual DB calls would be needed)
        enriched_results = []
        for res in search_results:
            meta = res.get("metadata", {})
            meta.get("engrams_item_id")
            meta.get("engrams_item_type")

            # Here you could fetch the full item from SQLite using item_id and item_type
            # For example:
            # if item_type == "decision" and item_id:
            #     full_item = db.get_decision_by_id(args.workspace_id, int(item_id)) # Assuming get_decision_by_id exists
            #     res["full_item_data"] = full_item.model_dump(mode='json') if full_item else None
            # else if item_type == "custom_data" and item_id:
            #     # For custom_data, ID is internal. Key and Category are in metadata.
            #     full_item_list = db.get_custom_data(args.workspace_id, category=meta.get("category"), key=meta.get("key"))
            #     if full_item_list:
            #         res["full_item_data"] = full_item_list[0].model_dump(mode='json')

            enriched_results.append(res)  # For now, just pass through

        return enriched_results

    except RuntimeError as re:  # Catch errors from embedding or vector store service
        log.error(f"Runtime error during semantic search: {re}", exc_info=True)
        raise ContextPortalError(f"Error during semantic search operation: {re}")
    except DatabaseError as dbe:  # Catch errors from SQLite if enriching results
        log.error(
            f"Database error during semantic search result enrichment: {dbe}",
            exc_info=True,
        )
        raise ContextPortalError(
            f"Database error processing semantic search results: {dbe}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in handle_semantic_search_engrams for workspace {args.workspace_id}"
        )
        raise ContextPortalError(
            f"Unexpected error during semantic search: {type(e).__name__}"
        )


# --- Export Tool Handler ---


def _format_product_context_md(data: Dict[str, Any]) -> str:
    lines = ["# Product Context\n"]
    for key, value in data.items():
        heading = key.replace("_", " ").title()
        lines.append(f"## {heading}\n")
        if isinstance(value, str):
            lines.append(value.strip() + "\n")
        elif isinstance(value, list):
            for item in value:
                lines.append(f"*   {item}\n")
        else:  # Fallback for other types
            lines.append(str(value) + "\n")
        lines.append("\n")
    return "".join(lines)


def _format_active_context_md(data: Dict[str, Any]) -> str:
    lines = ["# Active Context\n"]
    for key, value in data.items():
        heading = key.replace("_", " ").title()
        lines.append(f"## {heading}\n")
        if isinstance(value, str):
            lines.append(value.strip() + "\n")
        elif isinstance(value, list):
            for item in value:
                lines.append(f"*   {item}\n")
        else:  # Fallback for other types
            lines.append(str(value) + "\n")
        lines.append("\n")
    return "".join(lines)


def _decision_slug(summary: str) -> str:
    """Return a stable 12-char hex slug derived from the decision summary.

    Kept for backwards-compatibility when parsing older exports that contain
    ``<!-- slug:... -->`` comments instead of ``<!-- uuid:... -->`` comments.
    """
    return hashlib.sha256(summary.strip().lower().encode()).hexdigest()[:12]


def _format_decisions_md(decisions: List[models.Decision]) -> str:
    lines = ["# Decision Log\n"]
    for dec in sorted(decisions, key=lambda x: x.timestamp, reverse=True):
        lines.append("\n---\n")
        lines.append("## Decision\n")
        lines.append(
            f"*   [{dec.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {dec.summary}\n"
        )
        # Embed the decision's UUID so the import can do a stable upsert.
        # Fall back to a slug comment for decisions that predate the uuid column.
        if dec.uuid:
            lines.append(f"<!-- uuid:{dec.uuid} -->\n")
        else:
            slug = _decision_slug(dec.summary)
            lines.append(f"<!-- slug:{slug} -->\n")
        if dec.rationale:
            lines.append("\n## Rationale\n")
            lines.append(f"*   {dec.rationale}\n")
        if dec.implementation_details:
            lines.append("\n## Implementation Details\n")
            lines.append(f"*   {dec.implementation_details}\n")
    return "".join(lines)


def _format_progress_md(progress_entries: List[models.ProgressEntry]) -> str:
    lines = ["# Progress Log\n"]
    status_map = {"DONE": [], "IN_PROGRESS": [], "TODO": []}
    for entry in sorted(progress_entries, key=lambda x: x.timestamp, reverse=True):
        status_map.get(entry.status, status_map["TODO"]).append(entry)

    if status_map["DONE"]:
        lines.append("\n## Completed Tasks\n")
        for entry in status_map["DONE"]:
            lines.append(
                f"*   [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {entry.description}\n"
            )
    if status_map["IN_PROGRESS"]:
        lines.append("\n## In Progress Tasks\n")
        for entry in status_map["IN_PROGRESS"]:
            lines.append(
                f"*   [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {entry.description}\n"
            )
    if status_map["TODO"]:
        lines.append("\n## TODO Tasks\n")
        for entry in status_map["TODO"]:
            lines.append(
                f"*   [{entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {entry.description}\n"
            )
    return "".join(lines)


def _format_system_patterns_md(patterns: List[models.SystemPattern]) -> str:
    from datetime import timezone

    def _to_aware_utc(dt):
        # Treat naive as UTC for export consistency
        return (
            dt.replace(tzinfo=timezone.utc)
            if dt.tzinfo is None
            else dt.astimezone(timezone.utc)
        )

    lines = ["# System Patterns\n"]
    for pattern in sorted(
        patterns, key=lambda x: _to_aware_utc(x.timestamp), reverse=True
    ):  # Sort by timestamp
        lines.append("\n---\n")
        lines.append(f"## {pattern.name}\n")
        lines.append(
            f"*   [{pattern.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]\n"
        )  # Add timestamp
        if pattern.description:
            lines.append(f"{pattern.description}\n")
    return "".join(lines)


def handle_export_engrams_to_markdown(
    args: models.ExportEngramsToMarkdownArgs,
) -> Dict[str, Any]:
    """
    Exports Engrams data for a workspace to markdown files.

    When ``args.visibility_filter`` is set (e.g. ``'team'``), only items whose
    ``visibility`` column matches that value are included.  This makes the
    export suitable for committing to a shared Git repository — personal
    progress and individual notes are excluded, so only team-scoped decisions,
    patterns, and custom data land in the committed files.

    Assumes 'args' is an already validated Pydantic model instance.
    """
    workspace_path = Path(args.workspace_id)
    output_dir_name = args.output_path if args.output_path else "engrams_export"
    output_path = workspace_path / output_dir_name
    vf = args.visibility_filter  # None → export everything

    try:
        output_path.mkdir(parents=True, exist_ok=True)
        log.info(
            "Exporting Engrams data for workspace '%s' to '%s' (visibility_filter=%s)",
            args.workspace_id,
            output_path,
            vf or "all",
        )

        files_created = []

        # Product Context — only included in full (unfiltered) exports
        if vf is None:
            product_ctx_data = db.get_product_context(args.workspace_id).content
            if product_ctx_data:
                with open(
                    output_path / "product_context.md", "w", encoding="utf-8"
                ) as f:
                    f.write(_format_product_context_md(product_ctx_data))
                files_created.append("product_context.md")

            active_ctx_data = db.get_active_context(args.workspace_id).content
            if active_ctx_data:
                with open(
                    output_path / "active_context.md", "w", encoding="utf-8"
                ) as f:
                    f.write(_format_active_context_md(active_ctx_data))
                files_created.append("active_context.md")

            # Progress — personal by nature; only in full exports
            progress_entries = db.get_progress(args.workspace_id, limit=None)
            if progress_entries:
                with open(output_path / "progress_log.md", "w", encoding="utf-8") as f:
                    f.write(_format_progress_md(progress_entries))
                files_created.append("progress_log.md")

        # Decisions — visibility-filtered
        decisions = db.get_decisions(
            args.workspace_id, limit=None, visibility_filter=vf
        )
        if decisions:
            with open(output_path / "decision_log.md", "w", encoding="utf-8") as f:
                f.write(_format_decisions_md(decisions))
            files_created.append("decision_log.md")

        # System Patterns — visibility-filtered
        system_patterns = db.get_system_patterns(
            args.workspace_id, visibility_filter=vf
        )
        if system_patterns:
            with open(output_path / "system_patterns.md", "w", encoding="utf-8") as f:
                f.write(_format_system_patterns_md(system_patterns))
            files_created.append("system_patterns.md")

        # Custom Data — visibility-filtered
        custom_data_entries = db.get_custom_data(
            args.workspace_id, visibility_filter=vf
        )
        if custom_data_entries:
            custom_data_path = output_path / "custom_data"
            custom_data_path.mkdir(exist_ok=True)
            categories: Dict[str, List[str]] = {}
            for item in custom_data_entries:
                if item.category not in categories:
                    categories[item.category] = []
                # Always JSON-encode so the round-trip parser can use json.loads()
                # consistently regardless of whether the value is a string or dict.
                value_str = json.dumps(item.value, indent=2)
                categories[item.category].append(
                    f"### {item.key}\n\n*   [{item.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]\n\n```json\n{value_str}\n```\n"
                )

            for (
                category_name_from_loop,
                items_md,
            ) in categories.items():
                cat_file_name = (
                    "".join(c if c.isalnum() else "_" for c in category_name_from_loop)
                    + ".md"
                )
                with open(
                    custom_data_path / cat_file_name, "w", encoding="utf-8"
                ) as f:
                    f.write(
                        f"# Custom Data: {category_name_from_loop}\n\n"
                        + "\n---\n".join(items_md)
                    )
                files_created.append(f"custom_data/{cat_file_name}")

        return {
            "status": "success",
            "message": (
                f"Engrams data exported to '{output_path}' "
                f"(visibility_filter={vf or 'all'}). "
                f"Files created: {', '.join(files_created)}"
            ),
            "exported_path": str(output_path),
            "visibility_filter": vf,
            "file_count": len(files_created),
        }

    except DatabaseError as e:
        raise ContextPortalError(f"Database error during export: {e}")
    except IOError as e:
        raise ContextPortalError(
            f"File system error during export to '{output_path}': {e}"
        )
    except Exception as e:
        log.exception(
            "Unexpected error in export_engrams_to_markdown for workspace %s",
            args.workspace_id,
        )
        raise ContextPortalError(f"Unexpected error during export: {e}")


# --- Import Tool Handler ---


def _parse_key_value_markdown_section(section_content: str) -> str:
    """Helper to extract content from a simple markdown section."""
    lines = [
        line.strip() for line in section_content.strip().split("\n") if line.strip()
    ]
    # Remove potential list markers like '* '
    cleaned_lines = [re.sub(r"^\*   ", "", line) for line in lines]
    return "\n".join(cleaned_lines).strip()


def _parse_product_or_active_context_md(content: str) -> Dict[str, Any]:
    """Parses product_context.md or active_context.md content."""
    data = {}
    # Split by '## ' to get sections, ignoring the initial '# Title' part
    sections = re.split(r"\n## ", content)[1:]

    # First section is usually an introduction before the first '## '
    intro_match = re.match(
        r"^#\s\w+\sContext\n+(.*?)\n## ", content, re.DOTALL | re.MULTILINE
    )
    if intro_match:
        data["introduction"] = intro_match.group(1).strip()

    for section in sections:
        parts = section.split("\n", 1)
        heading_full = parts[0].strip()
        section_content = parts[1] if len(parts) > 1 else ""

        # Create a key from the heading (e.g., "Project Goal" -> "projectGoal")
        key = heading_full.replace(" ", "")
        key = key[0].lower() + key[1:] if key else ""

        if key:  # Ensure key is not empty
            # For "Recent Changes", we expect a list-like structure.
            if "Recent Changes" in heading_full:
                data[key] = _parse_key_value_markdown_section(
                    section_content
                )  # Keep as single string
            else:
                data[key] = _parse_key_value_markdown_section(section_content)
    return data


def _parse_decisions_md(content: str) -> List[Dict[str, Any]]:
    """Parses decision_log.md content.

    Each returned dict may include:
    - ``_uuid``: extracted from ``<!-- uuid:... -->`` (new format, preferred)
    - ``_slug``: extracted from ``<!-- slug:... -->`` (legacy format, fallback)

    The UUID is used for stable upsert during merge imports; the slug is kept
    for backwards-compatibility with older exports.
    """
    decisions = []
    # Split by '---' separator, then process each decision block
    decision_blocks = content.split("\n---\n")
    for block in decision_blocks:
        if not block.strip() or "## Decision" not in block:
            continue

        # Match only the single title line (no DOTALL so we stop at the newline)
        summary_match = re.search(r"## Decision\n\*\s*\[.*?\]\s*([^\n]+)", block)
        summary = summary_match.group(1).strip() if summary_match else "N/A"
        # Strip any embedded HTML comment that ended up on the same line
        summary = re.sub(r"\s*<!--\s*(?:uuid|slug):[^\s>]+\s*-->", "", summary).strip()

        # Prefer UUID comment; fall back to slug comment for legacy exports
        uuid_match = re.search(
            r"<!--\s*uuid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*-->",
            block,
        )
        slug_match = re.search(r"<!--\s*slug:([0-9a-f]+)\s*-->", block)
        decision_uuid = uuid_match.group(1) if uuid_match else None
        slug = slug_match.group(1) if slug_match else _decision_slug(summary)

        rationale_match = re.search(r"## Rationale\n\*\s*(.+)", block, re.DOTALL)
        rationale = rationale_match.group(1).strip() if rationale_match else None
        # Handle multi-line rationale
        if (
            rationale_match and rationale and "\n*" in rationale
        ):  # crude check for multi-bullet rationale
            rationale = "\n".join(
                [line.strip().lstrip("*").strip() for line in rationale.split("\n")]
            )

        impl_details_match = re.search(
            r"## Implementation Details\n\*\s*(.+)", block, re.DOTALL
        )
        impl_details = (
            impl_details_match.group(1).strip() if impl_details_match else None
        )
        if (
            impl_details_match and impl_details and "\n*" in impl_details
        ):  # crude check for multi-bullet details
            impl_details = "\n".join(
                [line.strip().lstrip("*").strip() for line in impl_details.split("\n")]
            )

        decisions.append(
            {
                "summary": summary,
                "rationale": rationale,
                "implementation_details": impl_details,
                "_uuid": decision_uuid,
                "_slug": slug,
            }
        )
    return decisions


def _parse_progress_md(content: str) -> List[Dict[str, str]]:
    """Parses progress_log.md content."""
    progress_items = []
    current_status = "TODO"  # Default

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## Completed Tasks"):
            current_status = "DONE"
        elif line.startswith("## In Progress Tasks") or line.startswith(
            "## Current Tasks"
        ):
            current_status = "IN_PROGRESS"
        elif line.startswith("## TODO Tasks") or line.startswith("## Next Steps"):
            current_status = "TODO"
        elif line.startswith("*"):
            description = re.sub(r"^\*\s*(\[.*?\]\s*)?", "", line).strip()
            if description:
                progress_items.append(
                    {"status": current_status, "description": description}
                )
    return progress_items


def _parse_system_patterns_md(content: str) -> List[Dict[str, str]]:
    """Parses system_patterns.md content."""
    patterns = []
    current_name = None
    current_desc_lines = []

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            if current_name:  # Save previous pattern
                patterns.append(
                    {
                        "name": current_name,
                        "description": "\n".join(current_desc_lines).strip() or None,
                    }
                )
                current_desc_lines = []
            current_name = line[3:].strip()
        elif current_name and line and not line.startswith("#"):
            current_desc_lines.append(line)

    if current_name:  # Save the last pattern
        patterns.append(
            {
                "name": current_name,
                "description": "\n".join(current_desc_lines).strip() or None,
            }
        )
    return patterns


def _parse_custom_data_category_md(
    content: str, category_name: str
) -> List[Dict[str, Any]]:
    """Parses a custom_data category markdown file."""
    items = []
    # Split by '### ' for keys, then parse the JSON block
    key_blocks = re.split(r"\n### ", content)
    for block in key_blocks:
        if not block.strip() or "```json" not in block:
            continue

        key_match = re.match(
            r"([^\n]+)\n.*?```json\n(.*?)\n```", block.strip(), re.DOTALL | re.MULTILINE
        )
        if key_match:
            key = key_match.group(1).strip()
            json_str_value = key_match.group(2).strip()
            try:
                value = json.loads(json_str_value)
                items.append({"category": category_name, "key": key, "value": value})
            except json.JSONDecodeError as e:
                log.warning(
                    f"Could not parse JSON for custom data {category_name}/{key}: {e}. Value: '{json_str_value}'"
                )
    return items


def _existing_decision_slugs(workspace_id: str) -> Set[str]:
    """Return the set of content-hash slugs for all decisions already in the DB.

    Used by the merge-import path as a fallback for legacy exports that carry
    ``<!-- slug:... -->`` comments instead of ``<!-- uuid:... -->`` comments.
    """
    existing = db.get_decisions(workspace_id, limit=None)
    return {_decision_slug(d.summary) for d in existing}


def _existing_decision_uuids(workspace_id: str) -> Set[str]:
    """Return the set of UUIDs for all decisions already in the DB."""
    existing = db.get_decisions(workspace_id, limit=None)
    return {d.uuid for d in existing if d.uuid}


def _existing_pattern_names(workspace_id: str) -> Set[str]:
    """Return the set of system-pattern names already in the DB (case-insensitive)."""
    existing = db.get_system_patterns(workspace_id)
    return {p.name.strip().lower() for p in existing}


def _existing_custom_data_keys(workspace_id: str) -> Set[str]:
    """Return a set of 'category::key' strings for all custom_data entries in the DB."""
    existing = db.get_custom_data(workspace_id)
    return {f"{e.category}::{e.key}" for e in existing}


def handle_import_markdown_to_engrams(
    args: models.ImportMarkdownToEngramsArgs,
) -> Dict[str, Any]:
    """
    Imports data from markdown files into Engrams for a workspace.

    When ``args.merge`` is ``True``, items that already exist locally are
    skipped rather than overwritten:

    - Decisions are identified by their content-hash slug (SHA-256 of the
      summary text, truncated to 12 hex chars).  A decision in the markdown
      file is skipped if a decision with the same slug is already in the DB.
    - System patterns are identified by name (case-insensitive).
    - Custom data entries are identified by ``category::key``.
    - Context files (product_context.md, active_context.md, progress_log.md)
      are always skipped in merge mode because they are personal/local state.

    When ``args.merge`` is ``False`` (the default), all items are inserted or
    replaced — identical to the previous behaviour.

    Assumes 'args' is an already validated Pydantic model instance.
    """
    workspace_path = Path(args.workspace_id)
    input_dir_name = args.input_path if args.input_path else "engrams_export"
    input_path = workspace_path / input_dir_name

    if not input_path.is_dir():
        raise ToolArgumentError(f"Input directory not found: {input_path}")

    log.info(
        "Importing Engrams data for workspace '%s' from '%s' (merge=%s)",
        args.workspace_id,
        input_path,
        args.merge,
    )
    summary_report: Dict[str, Any] = {
        "status": "success",
        "message": "Import process initiated.",
        "merge": args.merge,
        "files_processed": [],
        "items_logged": {},
        "items_skipped": {},
        "errors": [],
    }

    # Pre-load existing keys once if we're in merge mode (avoid N+1 queries)
    existing_uuids: Set[str] = (
        _existing_decision_uuids(args.workspace_id) if args.merge else set()
    )
    existing_slugs: Set[str] = (
        _existing_decision_slugs(args.workspace_id) if args.merge else set()
    )
    existing_patterns: Set[str] = (
        _existing_pattern_names(args.workspace_id) if args.merge else set()
    )
    existing_custom: Set[str] = (
        _existing_custom_data_keys(args.workspace_id) if args.merge else set()
    )

    # --- Context files (product_context.md, active_context.md, progress_log.md) ---
    # In merge mode these are skipped entirely — they represent local/personal state.
    context_file_map = {
        "product_context.md": (
            _parse_product_or_active_context_md,
            handle_update_product_context,
            models.UpdateContextArgs,
        ),
        "active_context.md": (
            _parse_product_or_active_context_md,
            handle_update_active_context,
            models.UpdateContextArgs,
        ),
        "progress_log.md": (
            _parse_progress_md,
            handle_log_progress,
            models.LogProgressArgs,
        ),
    }

    for filename, (parser_func, target_handler_func, pydantic_arg_model) in context_file_map.items():
        file_to_import = input_path / filename
        if not file_to_import.is_file():
            continue
        if args.merge:
            log.debug("merge mode: skipping context file %s", filename)
            summary_report["items_skipped"][filename] = "skipped (merge mode)"
            continue
        try:
            with open(file_to_import, "r", encoding="utf-8") as f:
                content_str = f.read()
            parsed_data = parser_func(content_str)
            summary_report["files_processed"].append(filename)
            item_type_key = filename.split(".")[0]

            if item_type_key in ("product_context", "active_context"):
                handler_call_args = pydantic_arg_model(
                    workspace_id=args.workspace_id, content=parsed_data
                )
                target_handler_func(handler_call_args)
                summary_report["items_logged"][item_type_key] = (
                    summary_report["items_logged"].get(item_type_key, 0) + 1
                )
            else:
                for item_data in parsed_data:
                    handler_call_args = pydantic_arg_model(
                        workspace_id=args.workspace_id, **item_data
                    )
                    target_handler_func(handler_call_args)
                    summary_report["items_logged"][item_type_key] = (
                        summary_report["items_logged"].get(item_type_key, 0) + 1
                    )
        except Exception as e:
            log.error("Error processing file %s: %s", filename, e)
            summary_report["errors"].append(f"Error processing {filename}: {str(e)}")

    # --- Decisions ---
    decision_file = input_path / "decision_log.md"
    if decision_file.is_file():
        try:
            with open(decision_file, "r", encoding="utf-8") as f:
                content_str = f.read()
            parsed_decisions = _parse_decisions_md(content_str)
            summary_report["files_processed"].append("decision_log.md")
            for item_data in parsed_decisions:
                decision_uuid = item_data.pop("_uuid", None)
                slug = item_data.pop("_slug", None)

                if args.merge:
                    if decision_uuid and decision_uuid in existing_uuids:
                        # UUID match → upsert: update the existing decision in place
                        log.debug("merge: upserting existing decision uuid=%s", decision_uuid)
                        upsert_data = models.Decision(
                            uuid=decision_uuid,
                            summary=item_data.get("summary", ""),
                            rationale=item_data.get("rationale"),
                            implementation_details=item_data.get("implementation_details"),
                            tags=None,
                            visibility=None,
                        )
                        db.update_decision(args.workspace_id, decision_uuid, upsert_data)
                        summary_report["items_logged"]["decision_log"] = (
                            summary_report["items_logged"].get("decision_log", 0) + 1
                        )
                        continue
                    elif not decision_uuid and slug and slug in existing_slugs:
                        # Legacy slug match (no UUID in export) → skip as before
                        log.debug("merge: skipping existing decision slug=%s (legacy)", slug)
                        summary_report["items_skipped"]["decision_log"] = (
                            summary_report["items_skipped"].get("decision_log", 0) + 1
                        )
                        continue

                # No match found — insert as a new decision
                # Carry the UUID from the markdown so we don't create a new one
                log_args_kwargs = dict(item_data)
                if decision_uuid:
                    log_args_kwargs["uuid"] = decision_uuid
                handler_call_args = models.LogDecisionArgs(
                    workspace_id=args.workspace_id, **log_args_kwargs
                )
                logged = handle_log_decision(handler_call_args)
                if args.merge:
                    if decision_uuid:
                        existing_uuids.add(decision_uuid)
                    elif slug:
                        existing_slugs.add(slug)
                summary_report["items_logged"]["decision_log"] = (
                    summary_report["items_logged"].get("decision_log", 0) + 1
                )
        except Exception as e:
            log.error("Error processing decision_log.md: %s", e)
            summary_report["errors"].append(f"Error processing decision_log.md: {str(e)}")

    # --- System Patterns ---
    patterns_file = input_path / "system_patterns.md"
    if patterns_file.is_file():
        try:
            with open(patterns_file, "r", encoding="utf-8") as f:
                content_str = f.read()
            parsed_patterns = _parse_system_patterns_md(content_str)
            summary_report["files_processed"].append("system_patterns.md")
            for item_data in parsed_patterns:
                name_key = item_data.get("name", "").strip().lower()
                if args.merge and name_key in existing_patterns:
                    log.debug("merge: skipping existing pattern name=%s", item_data.get("name"))
                    summary_report["items_skipped"]["system_patterns"] = (
                        summary_report["items_skipped"].get("system_patterns", 0) + 1
                    )
                    continue
                handler_call_args = models.LogSystemPatternArgs(
                    workspace_id=args.workspace_id, **item_data
                )
                handle_log_system_pattern(handler_call_args)
                if args.merge:
                    existing_patterns.add(name_key)
                summary_report["items_logged"]["system_patterns"] = (
                    summary_report["items_logged"].get("system_patterns", 0) + 1
                )
        except Exception as e:
            log.error("Error processing system_patterns.md: %s", e)
            summary_report["errors"].append(f"Error processing system_patterns.md: {str(e)}")

    # --- Custom Data ---
    custom_data_dir = input_path / "custom_data"
    if custom_data_dir.is_dir():
        summary_report["files_processed"].append("custom_data/*")
        for category_md_file in custom_data_dir.glob("*.md"):
            try:
                category_name = category_md_file.stem.replace("_", " ")
                with open(category_md_file, "r", encoding="utf-8") as f:
                    content_str = f.read()
                parsed_custom_items = _parse_custom_data_category_md(
                    content_str, category_name
                )
                for item_data in parsed_custom_items:
                    ck = f"{item_data.get('category')}::{item_data.get('key')}"
                    if args.merge and ck in existing_custom:
                        log.debug("merge: skipping existing custom_data %s", ck)
                        summary_report["items_skipped"]["custom_data"] = (
                            summary_report["items_skipped"].get("custom_data", 0) + 1
                        )
                        continue
                    handler_args = models.LogCustomDataArgs(
                        workspace_id=args.workspace_id, **item_data
                    )
                    handle_log_custom_data(handler_args)
                    if args.merge:
                        existing_custom.add(ck)
                    summary_report["items_logged"]["custom_data"] = (
                        summary_report["items_logged"].get("custom_data", 0) + 1
                    )
            except Exception as e:
                log.error(
                    "Error processing custom data file %s: %s",
                    category_md_file.name,
                    e,
                )
                summary_report["errors"].append(
                    f"Error processing {category_md_file.name}: {str(e)}"
                )

    summary_report["message"] = (
        f"Engrams data import from '{input_path}' complete "
        f"(merge={args.merge}). See details."
    )
    return summary_report


def handle_link_engrams_items(args: models.LinkEngramsItemsArgs) -> Dict[str, Any]:
    """
    Handles the 'link_engrams_items' MCP tool.
    Creates a link between two Engrams items.
    """
    try:
        link_to_create = models.ContextLink(
            source_item_type=args.source_item_type,
            source_item_id=args.source_item_id,
            target_item_type=args.target_item_type,
            target_item_id=args.target_item_id,
            relationship_type=args.relationship_type,
            description=args.description,
            # workspace_id is handled by the db function based on connection
            # timestamp is handled by Pydantic model default_factory
        )
        logged_link = db.log_context_link(args.workspace_id, link_to_create)
        return logged_link.model_dump(mode="json")
    except DatabaseError as e:
        raise ContextPortalError(f"Database error linking Engrams items: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in link_engrams_items for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error linking Engrams items: {e}")


def handle_get_linked_items(args: models.GetLinkedItemsArgs) -> List[Dict[str, Any]]:
    """
    Handles the 'get_linked_items' MCP tool.
    Retrieves links for a given Engrams item, with optional filters.
    """
    try:
        links_list = db.get_context_links(
            workspace_id=args.workspace_id,
            item_type=args.item_type,
            item_id=args.item_id,
            relationship_type_filter=args.relationship_type_filter,
            linked_item_type_filter=args.linked_item_type_filter,
            limit=args.limit,
        )
        return [link.model_dump(mode="json") for link in links_list]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error retrieving context links: {e}")
    except Exception as e:
        log.exception(
            f"Unexpected error in get_linked_items for workspace {args.workspace_id}"
        )
        raise ContextPortalError(f"Unexpected error retrieving context links: {e}")


def handle_get_item_history(args: models.GetItemHistoryArgs) -> List[Dict[str, Any]]:
    """
    Handles the 'get_item_history' MCP tool.
    Retrieves history for product_context or active_context.
    """
    try:
        # Pydantic model GetItemHistoryArgs already validates item_type
        history_entries = db.get_item_history(args.workspace_id, args)
        # The db.get_item_history function already returns a list of dicts
        # where content is a dict and timestamp is a datetime object.
        # We need to ensure timestamps are JSON serializable for the MCP response.

        serializable_history = []
        for entry in history_entries:
            entry_copy = entry.copy()  # Avoid modifying the original dict from db
            if isinstance(entry_copy.get("timestamp"), datetime):
                entry_copy["timestamp"] = entry_copy["timestamp"].isoformat()
            serializable_history.append(entry_copy)

        return serializable_history
    except (
        ValueError
    ) as e:  # From db function if item_type is somehow invalid post-Pydantic
        raise ToolArgumentError(str(e))
    except DatabaseError as e:
        raise ContextPortalError(
            f"Database error retrieving item history for {args.item_type}: {e}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in get_item_history for workspace {args.workspace_id}, item_type {args.item_type}"
        )
        raise ContextPortalError(f"Unexpected error retrieving item history: {e}")


# --- Batch Logging Handler ---

_SINGLE_ITEM_HANDLERS_MAP = {
    "decision": (handle_log_decision, models.LogDecisionArgs),
    "progress_entry": (handle_log_progress, models.LogProgressArgs),
    "system_pattern": (handle_log_system_pattern, models.LogSystemPatternArgs),
    "custom_data": (handle_log_custom_data, models.LogCustomDataArgs),
    # Add other loggable item types here if needed
}


def handle_batch_log_items(args: models.BatchLogItemsArgs) -> Dict[str, Any]:
    """
    Handles the 'batch_log_items' MCP tool.
    Logs multiple items of a specified type.
    """
    if args.item_type not in _SINGLE_ITEM_HANDLERS_MAP:
        raise ToolArgumentError(
            f"Unsupported item_type for batch logging: {args.item_type}. Supported types: {list(_SINGLE_ITEM_HANDLERS_MAP.keys())}"
        )

    handler_func, pydantic_model = _SINGLE_ITEM_HANDLERS_MAP[args.item_type]

    results = []
    errors = []
    success_count = 0
    failure_count = 0

    for i, item_data_dict in enumerate(args.items):
        try:
            # Each item_data_dict needs workspace_id for the Pydantic model
            item_args_with_ws = {"workspace_id": args.workspace_id, **item_data_dict}
            validated_item_args = pydantic_model(**item_args_with_ws)
            result = handler_func(validated_item_args)
            results.append(result)
            success_count += 1
        except ValidationError as ve:
            log.error(
                f"Validation error for item {i} in batch_log_items ({args.item_type}): {ve}"
            )
            errors.append({"item_index": i, "error": str(ve), "data": item_data_dict})
            failure_count += 1
        except ContextPortalError as cpe:
            log.error(
                f"ContextPortalError for item {i} in batch_log_items ({args.item_type}): {cpe}"
            )
            errors.append({"item_index": i, "error": str(cpe), "data": item_data_dict})
            failure_count += 1
        except Exception as e:
            log.exception(
                f"Unexpected error for item {i} in batch_log_items ({args.item_type})"
            )
            errors.append(
                {
                    "item_index": i,
                    "error": f"Unexpected server error: {type(e).__name__}",
                    "data": item_data_dict,
                }
            )
            failure_count += 1

    return {
        "status": (
            "partial_success"
            if success_count > 0 and failure_count > 0
            else ("success" if failure_count == 0 else "failure")
        ),
        "message": f"Batch log for '{args.item_type}': {success_count} succeeded, {failure_count} failed.",
        "successful_items": results,
        "failed_items": errors,
    }


# --- Deletion Tool Handlers ---


def handle_delete_decision_by_id(args: models.DeleteDecisionByIdArgs) -> Dict[str, Any]:
    """
    Handles the 'delete_decision_by_id' MCP tool.
    Deletes a decision by its ID.
    """
    try:
        deleted_from_db = db.delete_decision_by_id(args.workspace_id, args.decision_id)

        if deleted_from_db:
            try:
                vector_store_service.delete_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="decision",
                    item_id=str(args.decision_id),
                )
                log.info(
                    f"Successfully deleted embedding for decision ID {args.decision_id}"
                )
                return {
                    "status": "success",
                    "message": f"Decision ID {args.decision_id} and its embedding deleted successfully.",
                }
            except Exception as e_vec_del:
                log.error(
                    f"Failed to delete embedding for decision ID {args.decision_id} (DB record was deleted): {e_vec_del}",
                    exc_info=True,
                )
                # Return success for DB deletion but acknowledge embedding deletion failure.
                return {
                    "status": "partial_success",
                    "message": f"Decision ID {args.decision_id} deleted from database, but failed to delete its embedding: {e_vec_del}",
                }
        else:
            # This case means the ID was valid (e.g. integer) but not found in DB.
            # No need to attempt vector deletion if not found in DB.
            return {
                "status": "success",
                "message": f"Decision ID {args.decision_id} not found in database.",
            }
    except DatabaseError as e:
        raise ContextPortalError(
            f"Database error deleting decision ID {args.decision_id}: {e}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in delete_decision_by_id for workspace {args.workspace_id}, decision ID {args.decision_id}"
        )
        raise ContextPortalError(f"Unexpected error deleting decision: {e}")


def handle_delete_system_pattern_by_id(
    args: models.DeleteSystemPatternByIdArgs,
) -> Dict[str, Any]:
    """
    Handles the 'delete_system_pattern_by_id' MCP tool.
    Deletes a system pattern by its ID.
    """
    try:
        deleted_from_db = db.delete_system_pattern_by_id(
            args.workspace_id, args.pattern_id
        )

        if deleted_from_db:
            try:
                vector_store_service.delete_item_embedding(
                    workspace_id=args.workspace_id,
                    item_type="system_pattern",
                    item_id=str(args.pattern_id),
                )
                log.info(
                    f"Successfully deleted embedding for system pattern ID {args.pattern_id}"
                )
                return {
                    "status": "success",
                    "message": f"System pattern ID {args.pattern_id} and its embedding deleted successfully.",
                }
            except Exception as e_vec_del:
                log.error(
                    f"Failed to delete embedding for system pattern ID {args.pattern_id} (DB record was deleted): {e_vec_del}",
                    exc_info=True,
                )
                return {
                    "status": "partial_success",
                    "message": f"System pattern ID {args.pattern_id} deleted from database, but failed to delete its embedding: {e_vec_del}",
                }
        else:
            return {
                "status": "success",
                "message": f"System pattern ID {args.pattern_id} not found in database.",
            }
    except DatabaseError as e:
        raise ContextPortalError(
            f"Database error deleting system pattern ID {args.pattern_id}: {e}"
        )
    except Exception as e:
        log.exception(
            f"Unexpected error in delete_system_pattern_by_id for workspace {args.workspace_id}, pattern ID {args.pattern_id}"
        )
        raise ContextPortalError(f"Unexpected error deleting system pattern: {e}")


# --- Obsolete MCP Dispatcher Logic ---
# The following (TOOL_DESCRIPTIONS, handle_list_tools, TOOL_HANDLERS, dispatch_tool)
# are now obsolete as FastMCP handles tool registration, listing, and dispatch.
# They are removed to prevent confusion and ensure the new FastMCP mechanism is used.


# --- Governance Tool Handlers (Feature 1) ---


def handle_create_scope(args: gov_models.CreateScopeArgs) -> Dict[str, Any]:
    """Creates a new context scope (team or individual)."""
    try:
        scope = gov_models.ContextScope(
            scope_type=args.scope_type,
            scope_name=args.scope_name,
            parent_scope_id=args.parent_scope_id,
            created_by=args.created_by,
        )
        result = gov_db_ops.create_scope(args.workspace_id, scope)
        return {"status": "success", "scope": result.model_dump(mode="json")}
    except DatabaseError as e:
        raise ContextPortalError(f"Database error creating scope: {e}")
    except Exception as e:
        log.error("Error creating scope: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error creating scope: {e}")


def handle_get_scopes(args: gov_models.GetScopesArgs) -> List[Dict[str, Any]]:
    """Gets all context scopes, optionally filtered by type."""
    try:
        scopes = gov_db_ops.get_scopes(args.workspace_id, scope_type=args.scope_type)
        return [s.model_dump(mode="json") for s in scopes]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting scopes: {e}")
    except Exception as e:
        log.error("Error getting scopes: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting scopes: {e}")


def handle_log_governance_rule(
    args: gov_models.LogGovernanceRuleArgs,
) -> Dict[str, Any]:
    """Logs a new governance rule."""
    try:
        rule = gov_models.GovernanceRule(
            scope_id=args.scope_id,
            rule_type=args.rule_type,
            entity_type=args.entity_type,
            rule_definition=args.rule_definition,
            description=args.description,
        )
        result = gov_db_ops.log_governance_rule(args.workspace_id, rule)
        return {"status": "success", "rule": result.model_dump(mode="json")}
    except DatabaseError as e:
        raise ContextPortalError(f"Database error logging governance rule: {e}")
    except Exception as e:
        log.error("Error logging governance rule: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error logging governance rule: {e}")


def handle_get_governance_rules(
    args: gov_models.GetGovernanceRulesArgs,
) -> List[Dict[str, Any]]:
    """Gets governance rules for a scope, optionally filtered by entity type."""
    try:
        rules = gov_db_ops.get_governance_rules(
            args.workspace_id,
            scope_id=args.scope_id,
            entity_type=args.entity_type,
        )
        return [r.model_dump(mode="json") for r in rules]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting governance rules: {e}")
    except Exception as e:
        log.error("Error getting governance rules: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting governance rules: {e}")


def handle_check_compliance(args: gov_models.CheckComplianceArgs) -> Dict[str, Any]:
    """Manually checks an item against team governance rules."""
    try:
        # 1. Get the item's scope_id
        scope_id = gov_db_ops.get_item_scope_id(
            args.workspace_id, args.item_type, args.item_id
        )

        if scope_id is None:
            return {
                "status": "success",
                "result": gov_models.ConflictCheckResult(
                    has_conflict=False,
                    action="allow",
                    warnings=["Item has no scope assigned; governance check skipped."],
                ).model_dump(mode="json"),
            }

        # 2. Build item_data from the entity's raw row
        #    We need to query the item's data for the conflict detector
        table_map = {
            "decision": "decisions",
            "system_pattern": "system_patterns",
            "progress_entry": "progress_entries",
            "custom_data": "custom_data",
        }
        table = table_map.get(args.item_type)
        if not table:
            return {
                "status": "error",
                "error": f"Unsupported item_type for compliance check: {args.item_type}",
            }

        conn = db.get_db_connection(args.workspace_id)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (args.item_id,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            return {
                "status": "error",
                "error": f"{args.item_type} with id {args.item_id} not found.",
            }

        item_data = dict(row)
        # Parse tags if stored as JSON string
        if "tags" in item_data and isinstance(item_data["tags"], str):
            try:
                item_data["tags"] = json.loads(item_data["tags"])
            except (json.JSONDecodeError, TypeError):
                item_data["tags"] = []

        # 3. Run conflict detection
        check_result = conflict_detector.check_conflicts(
            workspace_id=args.workspace_id,
            item_type=args.item_type,
            item_data=item_data,
            scope_id=scope_id,
        )

        return {"status": "success", "result": check_result.model_dump(mode="json")}
    except DatabaseError as e:
        raise ContextPortalError(f"Database error checking compliance: {e}")
    except Exception as e:
        log.error("Error checking compliance: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error checking compliance: {e}")


def handle_check_planned_action(args: gov_models.CheckPlannedActionArgs) -> Dict[str, Any]:
    """Pre-mutation check: scans accepted decisions for conflicts with a planned action.

    This is the pre-check tool from Option E — agents call this BEFORE making
    workspace mutations. It checks the planned action description and tags against
    all accepted decisions using tag overlap and keyword matching.

    Unlike the post-write safety net in _apply_governance_checks(), this can
    return action='block' to prevent the mutation from happening.
    """
    try:
        # Build item_data dict from args to reuse check_decision_conflicts logic
        item_data = {
            "summary": args.action_description,
            "description": args.action_description,
            "tags": args.tags or [],
        }

        # Run the decision conflict check
        conflicts = conflict_detector.check_decision_conflicts(
            args.workspace_id, "planned_action", item_data
        )

        # For pre-mutation checks, upgrade warnings to blocks
        blocked = False
        blocking_decisions = []
        warnings_list = []

        if conflicts.has_conflict:
            for conflict in conflicts.conflicts:
                # All pre-mutation conflicts are blocking
                blocking_decisions.append({
                    "decision_id": conflict.get("decision_id"),
                    "decision_summary": conflict.get("decision_summary"),
                    "decision_uuid": conflict.get("decision_uuid"),
                    "overlapping_tags": conflict.get("overlapping_tags", []),
                    "message": conflict.get("message", ""),
                })
            blocked = True
            warnings_list = conflicts.warnings

        return {
            "blocked": blocked,
            "action": "block" if blocked else "allow",
            "conflicts": blocking_decisions,
            "warnings": warnings_list,
            "proceed": not blocked,
            "checked_against_decisions": True,
            "message": (
                f"BLOCKED: {len(blocking_decisions)} accepted decision(s) conflict with this action. "
                "Review the conflicts and seek explicit override before proceeding."
                if blocked
                else "No conflicts detected with accepted decisions. Proceed."
            ),
        }
    except Exception as e:
        log.warning("check_planned_action failed: %s", e)
        return {
            "blocked": False,
            "action": "allow",
            "conflicts": [],
            "warnings": [f"Pre-check failed (non-fatal): {e}. Proceed with caution."],
            "proceed": True,
            "checked_against_decisions": False,
            "message": f"Pre-check encountered an error: {e}. Proceeding without governance check.",
        }


def handle_get_scope_amendments(
    args: gov_models.GetScopeAmendmentsArgs,
) -> List[Dict[str, Any]]:
    """Gets scope amendments with optional filters."""
    try:
        amendments = gov_db_ops.get_scope_amendments(
            args.workspace_id,
            status=args.status,
            scope_id=args.scope_id,
        )
        return [a.model_dump(mode="json") for a in amendments]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting scope amendments: {e}")
    except Exception as e:
        log.error("Error getting scope amendments: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting scope amendments: {e}")


def handle_review_amendment(args: gov_models.ReviewAmendmentArgs) -> Dict[str, Any]:
    """Reviews (accepts or rejects) a scope amendment."""
    try:
        updated = gov_db_ops.review_amendment(
            args.workspace_id,
            amendment_id=args.amendment_id,
            status=args.status,
            reviewed_by=args.reviewed_by,
        )
        if updated:
            return {
                "status": "success",
                "message": f"Amendment {args.amendment_id} updated to '{args.status}' by {args.reviewed_by}.",
            }
        else:
            return {
                "status": "success",
                "message": f"Amendment {args.amendment_id} not found.",
            }
    except DatabaseError as e:
        raise ContextPortalError(f"Database error reviewing amendment: {e}")
    except Exception as e:
        log.error("Error reviewing amendment: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error reviewing amendment: {e}")


def handle_get_effective_context(
    args: gov_models.GetEffectiveContextArgs,
) -> Dict[str, Any]:
    """Gets merged team + individual context for a developer scope.

    Retrieves the individual scope, finds its parent team scope,
    queries decisions/patterns/custom_data for both scopes, and merges
    them with team items listed first (taking precedence).
    """
    try:
        # 1. Get the individual scope
        individual_scope = gov_db_ops.get_scope_by_id(args.workspace_id, args.scope_id)
        if not individual_scope:
            return {"status": "error", "error": f"Scope {args.scope_id} not found."}

        if individual_scope.scope_type != "individual":
            return {
                "status": "error",
                "error": f"Scope {args.scope_id} is not an individual scope (type: {individual_scope.scope_type}).",
            }

        team_scope_id = individual_scope.parent_scope_id
        team_scope = None
        if team_scope_id:
            team_scope = gov_db_ops.get_scope_by_id(args.workspace_id, team_scope_id)

        conn = db.get_db_connection(args.workspace_id)
        cursor = conn.cursor()

        effective = {
            "individual_scope": individual_scope.model_dump(mode="json"),
            "team_scope": team_scope.model_dump(mode="json") if team_scope else None,
            "decisions": [],
            "system_patterns": [],
            "custom_data": [],
        }

        # Helper to query items by scope
        def _get_items_for_scope(table: str, scope_id: int) -> List[Dict[str, Any]]:
            cursor.execute(f"SELECT * FROM {table} WHERE scope_id = ?", (scope_id,))
            return [dict(r) for r in cursor.fetchall()]

        # 2. Get team-scope items (listed first for precedence)
        if team_scope_id:
            team_decisions = _get_items_for_scope("decisions", team_scope_id)
            team_patterns = _get_items_for_scope("system_patterns", team_scope_id)
            team_custom = _get_items_for_scope("custom_data", team_scope_id)
            for item in team_decisions:
                item["_source_scope"] = "team"
            for item in team_patterns:
                item["_source_scope"] = "team"
            for item in team_custom:
                item["_source_scope"] = "team"
            effective["decisions"].extend(team_decisions)
            effective["system_patterns"].extend(team_patterns)
            effective["custom_data"].extend(team_custom)

        # 3. Get individual-scope items (appended after team items)
        ind_decisions = _get_items_for_scope("decisions", args.scope_id)
        ind_patterns = _get_items_for_scope("system_patterns", args.scope_id)
        ind_custom = _get_items_for_scope("custom_data", args.scope_id)
        for item in ind_decisions:
            item["_source_scope"] = "individual"
        for item in ind_patterns:
            item["_source_scope"] = "individual"
        for item in ind_custom:
            item["_source_scope"] = "individual"
        effective["decisions"].extend(ind_decisions)
        effective["system_patterns"].extend(ind_patterns)
        effective["custom_data"].extend(ind_custom)

        cursor.close()

        return {"status": "success", "effective_context": effective}
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting effective context: {e}")
    except Exception as e:
        log.error("Error getting effective context: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting effective context: {e}")


# --- Code Bindings Tool Handlers (Feature 2) ---


def handle_bind_code_to_item(args: binding_models.BindCodeToItemArgs) -> Dict[str, Any]:
    """Creates a code binding between a Engrams entity and file patterns."""
    try:
        binding = binding_models.CodeBinding(
            item_type=args.item_type,
            item_id=args.item_id,
            file_pattern=args.file_pattern,
            symbol_pattern=args.symbol_pattern,
            binding_type=args.binding_type,
            confidence=args.confidence,
        )
        result = binding_db_ops.create_code_binding(args.workspace_id, binding)
        # Write-through: update .engrams/ file frontmatter for team entities
        try:
            _update_binding_in_file(args.workspace_id, args.item_type, args.item_id)
        except Exception as e_wt:
            log.warning(
                "Write-through failed for binding on %s/%s: %s",
                args.item_type,
                args.item_id,
                e_wt,
            )
        return {"status": "success", "binding": result.model_dump(mode="json")}
    except DatabaseError as e:
        raise ContextPortalError(f"Database error creating code binding: {e}")
    except Exception as e:
        log.error("Error creating code binding: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error creating code binding: {e}")


def handle_get_bindings_for_item(
    args: binding_models.GetBindingsForItemArgs,
) -> List[Dict[str, Any]]:
    """Gets all code bindings for a Engrams entity."""
    try:
        bindings = binding_db_ops.get_bindings_for_item(
            args.workspace_id, args.item_type, args.item_id
        )
        return [b.model_dump(mode="json") for b in bindings]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting bindings: {e}")
    except Exception as e:
        log.error("Error getting bindings for item: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting bindings: {e}")


def handle_get_context_for_files(
    args: binding_models.GetContextForFilesArgs,
) -> Dict[str, Any]:
    """Get all Engrams entities bound to the given file paths."""
    try:
        matched_bindings = binding_db_ops.get_bindings_matching_files(
            args.workspace_id,
            args.file_paths,
            binding_type_filter=args.binding_type_filter,
        )

        # Deduplicate and group by entity type
        seen = set()
        grouped: Dict[str, list] = {}
        for binding in matched_bindings:
            key = f"{binding.item_type}:{binding.item_id}"
            if key in seen:
                continue
            seen.add(key)

            summary = binding_db_ops.get_entity_summary(
                args.workspace_id, binding.item_type, binding.item_id
            )
            entry = {
                "item_type": binding.item_type,
                "item_id": binding.item_id,
                "summary": summary,
                "binding_type": binding.binding_type,
                "confidence": binding.confidence,
                "file_pattern": binding.file_pattern,
            }
            grouped.setdefault(binding.item_type, []).append(entry)

        return {"status": "success", "context": grouped, "total_entities": len(seen)}
    except Exception as e:
        log.error("Error getting context for files: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_verify_bindings(args: binding_models.VerifyBindingsArgs) -> Dict[str, Any]:
    """Verify which bindings still match actual files."""
    try:
        if args.item_type and args.item_id:
            bindings = binding_db_ops.get_bindings_for_item(
                args.workspace_id, args.item_type, args.item_id
            )
        else:
            bindings = binding_db_ops.get_all_bindings(args.workspace_id)

        results = []
        for binding in bindings:
            status, files_matched, notes = binding_matcher.verify_binding_pattern(
                args.workspace_id, binding.file_pattern, binding.symbol_pattern
            )
            # Log the verification
            verif = binding_models.CodeBindingVerification(
                binding_id=binding.id,
                verification_status=status,
                files_matched=files_matched,
                notes=notes,
            )
            binding_db_ops.log_binding_verification(args.workspace_id, verif)
            results.append(
                {
                    "binding_id": binding.id,
                    "file_pattern": binding.file_pattern,
                    "status": status,
                    "files_matched": files_matched,
                    "notes": notes,
                }
            )

        return {
            "status": "success",
            "verifications": results,
            "total_checked": len(results),
        }
    except Exception as e:
        log.error("Error verifying bindings: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_get_stale_bindings(
    args: binding_models.GetStaleBindingsArgs,
) -> List[Dict[str, Any]]:
    """Gets bindings that haven't been verified recently or failed verification."""
    try:
        bindings = binding_db_ops.get_stale_bindings(
            args.workspace_id, days_stale=args.days_stale
        )
        return [b.model_dump(mode="json") for b in bindings]
    except DatabaseError as e:
        raise ContextPortalError(f"Database error getting stale bindings: {e}")
    except Exception as e:
        log.error("Error getting stale bindings: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error getting stale bindings: {e}")


def handle_suggest_bindings(args: binding_models.SuggestBindingsArgs) -> Dict[str, Any]:
    """Analyzes entity text content and suggests likely file patterns."""
    try:
        suggestions = binding_db_ops.suggest_bindings_for_item(
            args.workspace_id, args.item_type, args.item_id
        )
        return {
            "status": "success",
            "item_type": args.item_type,
            "item_id": args.item_id,
            "suggested_patterns": suggestions,
        }
    except DatabaseError as e:
        raise ContextPortalError(f"Database error suggesting bindings: {e}")
    except Exception as e:
        log.error("Error suggesting bindings: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error suggesting bindings: {e}")


def handle_unbind_code_from_item(
    args: binding_models.UnbindCodeFromItemArgs,
) -> Dict[str, Any]:
    """Removes a code binding by its ID."""
    try:
        # Fetch binding info BEFORE deletion for write-through
        binding_info = binding_db_ops.get_binding_by_id(args.workspace_id, args.binding_id)
        deleted = binding_db_ops.delete_code_binding(args.workspace_id, args.binding_id)
        if deleted and binding_info:
            try:
                _update_binding_in_file(
                    args.workspace_id, binding_info.item_type, binding_info.item_id
                )
            except Exception as e_wt:
                log.warning(
                    "Write-through failed removing binding %s: %s", args.binding_id, e_wt
                )
        if deleted:
            return {
                "status": "success",
                "message": f"Binding {args.binding_id} deleted.",
            }
        else:
            return {
                "status": "success",
                "message": f"Binding {args.binding_id} not found.",
            }
    except DatabaseError as e:
        raise ContextPortalError(f"Database error deleting binding: {e}")
    except Exception as e:
        log.error("Error deleting binding: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error deleting binding: {e}")


def _update_binding_in_file(workspace_id: str, item_type: str, item_id: int) -> None:
    """Private helper: update the ``.engrams/`` file frontmatter after a binding add/remove.

    Fetches the entity from DB, checks ``visibility == 'team'``, gets all current
    bindings, then calls the appropriate write-through updater.

    Silently skips non-team entities — this is intentional (individual/personal
    bindings remain DB-only).
    """
    if item_type == "decision":
        entity = db.get_decision_by_id(workspace_id, item_id)
        if entity is None or getattr(entity, "visibility", None) != "team":
            return
        current_bindings = binding_db_ops.get_bindings_for_item(
            workspace_id, item_type, item_id
        )
        write_through.update_decision_bindings(workspace_id, entity, current_bindings)
    elif item_type == "system_pattern":
        entity = db.get_system_pattern_by_id(workspace_id, item_id)
        if entity is None or getattr(entity, "visibility", None) != "team":
            return
        current_bindings = binding_db_ops.get_bindings_for_item(
            workspace_id, item_type, item_id
        )
        write_through.update_pattern_bindings(workspace_id, entity, current_bindings)
    # Other item types (progress_entry, custom_data) do not have binding file support


# --- Context Budgeting Tool Handlers (Feature 3) ---


def _gather_all_entities(workspace_id: str) -> List[Dict[str, Any]]:
    """Gather all Engrams entities from the workspace as tagged dicts."""
    candidates: List[Dict[str, Any]] = []

    # Decisions
    try:
        decisions = db.get_decisions(workspace_id, limit=500)
        for d in decisions:
            entity = d.model_dump(mode="json") if hasattr(d, "model_dump") else dict(d)
            entity["_type"] = "decision"
            candidates.append(entity)
    except Exception as e:
        log.warning("Error gathering decisions for budgeting: %s", e)

    # System patterns
    try:
        patterns = db.get_system_patterns(workspace_id)
        for p in patterns:
            entity = p.model_dump(mode="json") if hasattr(p, "model_dump") else dict(p)
            entity["_type"] = "system_pattern"
            candidates.append(entity)
    except Exception as e:
        log.warning("Error gathering system patterns for budgeting: %s", e)

    # Progress entries
    try:
        progress = db.get_progress(workspace_id, limit=500)
        for pr in progress:
            entity = (
                pr.model_dump(mode="json") if hasattr(pr, "model_dump") else dict(pr)
            )
            entity["_type"] = "progress"
            candidates.append(entity)
    except Exception as e:
        log.warning("Error gathering progress for budgeting: %s", e)

    # Custom data
    try:
        custom = db.get_custom_data(workspace_id)
        for c in custom:
            entity = c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)
            entity["_type"] = "custom_data"
            candidates.append(entity)
    except Exception as e:
        log.warning("Error gathering custom data for budgeting: %s", e)

    return candidates


def _compute_link_counts(
    workspace_id: str, candidates: List[Dict[str, Any]]
) -> Dict[str, int]:
    """Pre-compute link counts for all candidate entities."""
    link_counts: Dict[str, int] = {}
    for entity in candidates:
        key = f"{entity['_type']}:{entity.get('id', 0)}"
        try:
            links = db.get_context_links(
                workspace_id, item_type=entity["_type"], item_id=entity.get("id")
            )
            link_counts[key] = len(links)
        except Exception:
            link_counts[key] = 0
    return link_counts


def handle_get_relevant_context(
    args: budget_models.GetRelevantContextArgs,
) -> Dict[str, Any]:
    """Get budget-optimized relevant context for a task."""
    try:
        # 1. Gather all entities
        candidates = _gather_all_entities(args.workspace_id)

        # 2. Pre-compute link counts for centrality
        link_counts = _compute_link_counts(args.workspace_id, candidates)

        # 3. Get bound entity keys if file_paths provided
        bound_entity_keys: set = set()
        if args.file_paths:
            try:
                matched = binding_db_ops.get_bindings_matching_files(
                    args.workspace_id, args.file_paths
                )
                for b in matched:
                    bound_entity_keys.add(f"{b.item_type}:{b.item_id}")
            except Exception:
                pass  # Bindings feature may not be available

        # 4. Score entities
        scored = score_entities(
            entities=candidates,
            task_description=args.task_description,
            file_paths=args.file_paths,
            profile=args.profile or "task_focused",
            workspace_id=args.workspace_id,
            link_counts=link_counts,
            bound_entity_keys=bound_entity_keys,
        )

        # 5. Select within budget
        budget_result = select_context(
            candidates=scored,
            token_budget=args.token_budget,
            format_preference=args.format or "standard",
        )

        return {"status": "success", **budget_result.to_dict()}
    except Exception as e:
        log.error("Error getting relevant context: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_estimate_context_size(
    args: budget_models.EstimateContextSizeArgs,
) -> Dict[str, Any]:
    """Preview context size and recommended budgets."""
    try:
        # 1. Gather entities
        candidates = _gather_all_entities(args.workspace_id)

        # 2. Score (to get entities with token estimates)
        scored = score_entities(
            entities=candidates,
            task_description=args.task_description,
            profile=args.profile or "task_focused",
            workspace_id=args.workspace_id,
        )

        result = estimate_context_size(scored)
        return {"status": "success", **result}
    except Exception as e:
        log.error("Error estimating context size: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_get_context_budget_config(
    args: budget_models.GetContextBudgetConfigArgs,
) -> Dict[str, Any]:
    """Get current scoring weights configuration."""
    try:
        # Try to load from custom data
        custom = db.get_custom_data(
            args.workspace_id, category="_engrams_config", key="budget_weights"
        )
        if custom:
            stored = custom[0]
            value = (
                stored.value if hasattr(stored, "value") else stored.get("value", "{}")
            )
            if isinstance(value, str):
                weights = json.loads(value)
            else:
                weights = value
            return {"status": "success", "weights": weights, "source": "custom"}
        else:
            return {
                "status": "success",
                "weights": dict(DEFAULT_WEIGHTS),
                "source": "default",
            }
    except Exception as e:
        log.error("Error getting budget config: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_update_context_budget_config(
    args: budget_models.UpdateContextBudgetConfigArgs,
) -> Dict[str, Any]:
    """Update scoring weights configuration."""
    try:
        # Merge with defaults
        current_weights = dict(DEFAULT_WEIGHTS)
        current_weights.update(args.weights)

        data = models.CustomData(
            category="_engrams_config",
            key="budget_weights",
            value=json.dumps(current_weights),
        )
        db.log_custom_data(args.workspace_id, data)
        return {"status": "success", "weights": current_weights}
    except Exception as e:
        log.error("Error updating budget config: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# --- Project Onboarding Tool Handlers (Feature 4) ---


def handle_get_project_briefing(
    args: onboarding_models.GetProjectBriefingArgs,
) -> Dict[str, Any]:
    """Generate a project briefing at the specified level."""
    try:
        result = onboarding_briefing.generate_briefing(
            workspace_id=args.workspace_id,
            level=args.level,
            token_budget=args.token_budget,
            sections=args.sections,
            scope_id=args.scope_id,
        )
        return {"status": "success", **result}
    except Exception as e:
        log.error("Error generating project briefing: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_get_briefing_staleness(
    args: onboarding_models.GetBriefingStalenessArgs,
) -> Dict[str, Any]:
    """Check how fresh the briefing data is."""
    try:
        result = onboarding_briefing.check_briefing_staleness(
            workspace_id=args.workspace_id,
            stale_threshold_days=args.stale_threshold_days or 30,
        )
        return {"status": "success", **result}
    except Exception as e:
        log.error("Error checking briefing staleness: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_get_section_detail(
    args: onboarding_models.GetSectionDetailArgs,
) -> Dict[str, Any]:
    """Get detailed content for a specific briefing section."""
    try:
        result = onboarding_briefing.get_section_detail(
            workspace_id=args.workspace_id,
            section_id=args.section_id,
            token_budget=args.token_budget,
            scope_id=args.scope_id,
        )
        return result
    except Exception as e:
        log.error("Error getting section detail: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


def handle_index_sync(args) -> Dict[str, Any]:
    """Triggers TeamContentIndexer.scan_and_sync() or incremental_sync().

    Called by the ``engrams-mcp index-sync`` CLI command, which is installed
    by the post-merge git hook in filesystem-first mode.

    Args:
        args: An object with ``workspace_id`` (str) and optionally ``files``
              (list of file path strings).  Accepts Pydantic model instances,
              argparse namespaces, or any duck-typed object.

    Returns:
        A dict with status, counts, and any error messages.
    """
    from pathlib import Path as _Path

    from ..team_sync.indexer import TeamContentIndexer

    try:
        workspace_id = args.workspace_id
        files = getattr(args, "files", None) or []

        indexer = TeamContentIndexer(workspace_id)

        if files:
            changed = [
                _Path(f) if _Path(f).is_absolute() else _Path(workspace_id) / f
                for f in files
            ]
            report = indexer.incremental_sync(changed)
        else:
            report = indexer.scan_and_sync()

        return {
            "status": "success",
            "files_processed": report.files_processed,
            "decisions_upserted": report.decisions_upserted,
            "patterns_upserted": report.patterns_upserted,
            "custom_data_upserted": report.custom_data_upserted,
            "bindings_added": report.bindings_added,
            "bindings_removed": report.bindings_removed,
            "files_skipped": report.files_skipped,
            "errors": report.errors,
        }
    except Exception as e:
        log.error("Error in handle_index_sync: %s", e, exc_info=True)
        raise ContextPortalError(f"Unexpected error in index_sync: {e}")
