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

"""Database operations for the governance feature (Feature 1)."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..core.exceptions import DatabaseError
from ..db.database import get_db_connection
from . import models as gov_models

log = logging.getLogger(__name__)


# --- Context Scopes CRUD ---


def create_scope(
    workspace_id: str, scope: gov_models.ContextScope
) -> gov_models.ContextScope:
    """Creates a new context scope."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        INSERT INTO context_scopes (scope_type, scope_name, parent_scope_id, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                scope.scope_type,
                scope.scope_name,
                scope.parent_scope_id,
                scope.created_by,
                scope.created_at,
            ),
        )
        scope.id = cursor.lastrowid
        conn.commit()
        return scope
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to create scope: {e}")
    finally:
        if cursor:
            cursor.close()


def get_scopes(
    workspace_id: str, scope_type: Optional[str] = None
) -> List[gov_models.ContextScope]:
    """Retrieves context scopes, optionally filtered by type."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = "SELECT id, scope_type, scope_name, parent_scope_id, created_by, created_at FROM context_scopes"
    params: List[Any] = []

    if scope_type:
        sql += " WHERE scope_type = ?"
        params.append(scope_type)

    sql += " ORDER BY id ASC"

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        return [
            gov_models.ContextScope(
                id=row["id"],
                scope_type=row["scope_type"],
                scope_name=row["scope_name"],
                parent_scope_id=row["parent_scope_id"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get scopes: {e}")
    finally:
        if cursor:
            cursor.close()


def get_scope_by_id(
    workspace_id: str, scope_id: int
) -> Optional[gov_models.ContextScope]:
    """Retrieves a single scope by ID."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = "SELECT id, scope_type, scope_name, parent_scope_id, created_by, created_at FROM context_scopes WHERE id = ?"
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (scope_id,))
        row = cursor.fetchone()
        if row:
            return gov_models.ContextScope(
                id=row["id"],
                scope_type=row["scope_type"],
                scope_name=row["scope_name"],
                parent_scope_id=row["parent_scope_id"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
        return None
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get scope {scope_id}: {e}")
    finally:
        if cursor:
            cursor.close()


# --- Governance Rules CRUD ---


def log_governance_rule(
    workspace_id: str, rule: gov_models.GovernanceRule
) -> gov_models.GovernanceRule:
    """Creates a new governance rule."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        INSERT INTO governance_rules (scope_id, rule_type, entity_type, rule_definition,
                                       description, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                rule.scope_id,
                rule.rule_type,
                rule.entity_type,
                json.dumps(rule.rule_definition),
                rule.description,
                1 if rule.is_active else 0,
                rule.created_at,
                rule.updated_at,
            ),
        )
        rule.id = cursor.lastrowid
        conn.commit()
        return rule
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to log governance rule: {e}")
    finally:
        if cursor:
            cursor.close()


def get_governance_rules(
    workspace_id: str,
    scope_id: int,
    entity_type: Optional[str] = None,
    active_only: bool = True,
) -> List[gov_models.GovernanceRule]:
    """Retrieves governance rules for a scope."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = "SELECT id, scope_id, rule_type, entity_type, rule_definition, description, is_active, created_at, updated_at FROM governance_rules WHERE scope_id = ?"
    params: List[Any] = [scope_id]

    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)

    if active_only:
        sql += " AND is_active = 1"

    sql += " ORDER BY id ASC"

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        return [
            gov_models.GovernanceRule(
                id=row["id"],
                scope_id=row["scope_id"],
                rule_type=row["rule_type"],
                entity_type=row["entity_type"],
                rule_definition=json.loads(row["rule_definition"]),
                description=row["description"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    except (sqlite3.Error, json.JSONDecodeError) as e:
        raise DatabaseError(f"Failed to get governance rules: {e}")
    finally:
        if cursor:
            cursor.close()


def get_team_rules_for_entity_type(
    workspace_id: str, entity_type: str
) -> List[gov_models.GovernanceRule]:
    """Retrieves all active team-scope governance rules for a given entity type."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        SELECT gr.id, gr.scope_id, gr.rule_type, gr.entity_type, gr.rule_definition,
               gr.description, gr.is_active, gr.created_at, gr.updated_at
        FROM governance_rules gr
        JOIN context_scopes cs ON gr.scope_id = cs.id
        WHERE cs.scope_type = 'team'
          AND gr.entity_type = ?
          AND gr.is_active = 1
        ORDER BY gr.id ASC
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (entity_type,))
        rows = cursor.fetchall()
        return [
            gov_models.GovernanceRule(
                id=row["id"],
                scope_id=row["scope_id"],
                rule_type=row["rule_type"],
                entity_type=row["entity_type"],
                rule_definition=json.loads(row["rule_definition"]),
                description=row["description"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    except (sqlite3.Error, json.JSONDecodeError) as e:
        raise DatabaseError(f"Failed to get team rules: {e}")
    finally:
        if cursor:
            cursor.close()


# --- Scope Amendments CRUD ---


def create_scope_amendment(
    workspace_id: str, amendment: gov_models.ScopeAmendment
) -> gov_models.ScopeAmendment:
    """Creates a new scope amendment."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        INSERT INTO scope_amendments (source_item_type, source_item_id, target_item_type,
                                       target_item_id, status, rationale, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                amendment.source_item_type,
                amendment.source_item_id,
                amendment.target_item_type,
                amendment.target_item_id,
                amendment.status,
                amendment.rationale,
                amendment.created_at,
            ),
        )
        amendment.id = cursor.lastrowid
        conn.commit()
        return amendment
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to create scope amendment: {e}")
    finally:
        if cursor:
            cursor.close()


def get_scope_amendments(
    workspace_id: str, status: Optional[str] = None, scope_id: Optional[int] = None
) -> List[gov_models.ScopeAmendment]:
    """Retrieves scope amendments with optional filters."""
    conn = get_db_connection(workspace_id)
    cursor = None

    # If filtering by scope_id, we need to join with the entity tables
    # For simplicity, we'll filter by status only at the SQL level
    sql = "SELECT id, source_item_type, source_item_id, target_item_type, target_item_id, status, rationale, reviewed_by, reviewed_at, created_at FROM scope_amendments"
    conditions: List[str] = []
    params: List[Any] = []

    if status:
        conditions.append("status = ?")
        params.append(status)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY created_at DESC"

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        return [
            gov_models.ScopeAmendment(
                id=row["id"],
                source_item_type=row["source_item_type"],
                source_item_id=row["source_item_id"],
                target_item_type=row["target_item_type"],
                target_item_id=row["target_item_id"],
                status=row["status"],
                rationale=row["rationale"],
                reviewed_by=row["reviewed_by"],
                reviewed_at=row["reviewed_at"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get scope amendments: {e}")
    finally:
        if cursor:
            cursor.close()


def review_amendment(
    workspace_id: str, amendment_id: int, status: str, reviewed_by: str
) -> bool:
    """Reviews (accepts or rejects) a scope amendment."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        UPDATE scope_amendments
        SET status = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            sql, (status, reviewed_by, datetime.now(timezone.utc), amendment_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to review amendment {amendment_id}: {e}")
    finally:
        if cursor:
            cursor.close()


# --- Governance Column Operations ---


def get_item_scope_id(workspace_id: str, item_type: str, item_id: int) -> Optional[int]:
    """Gets the scope_id for an entity in its table."""
    table_map = {
        "decision": "decisions",
        "system_pattern": "system_patterns",
        "progress_entry": "progress_entries",
        "custom_data": "custom_data",
    }
    table = table_map.get(item_type)
    if not table:
        return None

    conn = get_db_connection(workspace_id)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT scope_id FROM {table} WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return row["scope_id"] if row else None
    except sqlite3.Error:
        return None
    finally:
        if cursor:
            cursor.close()


def update_item_override_status(
    workspace_id: str, item_type: str, item_id: int, override_status: str
) -> bool:
    """Updates the override_status for an entity."""
    table_map = {
        "decision": "decisions",
        "system_pattern": "system_patterns",
        "progress_entry": "progress_entries",
        "custom_data": "custom_data",
    }
    table = table_map.get(item_type)
    if not table:
        return False

    conn = get_db_connection(workspace_id)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE {table} SET override_status = ? WHERE id = ?",
            (override_status, item_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to update override status: {e}")
    finally:
        if cursor:
            cursor.close()


def get_team_items_by_type(workspace_id: str, entity_type: str) -> List[Dict[str, Any]]:
    """Gets all team-scope items of a given type (for conflict detection)."""
    table_map = {
        "decision": "decisions",
        "system_pattern": "system_patterns",
        "progress_entry": "progress_entries",
        "custom_data": "custom_data",
    }
    table = table_map.get(entity_type)
    if not table:
        return []

    conn = get_db_connection(workspace_id)
    cursor = None
    sql = f"""
        SELECT d.*, cs.scope_type
        FROM {table} d
        JOIN context_scopes cs ON d.scope_id = cs.id
        WHERE cs.scope_type = 'team'
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        if cursor:
            cursor.close()
