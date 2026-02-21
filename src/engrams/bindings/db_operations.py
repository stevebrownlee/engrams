"""Database operations for code bindings (Feature 2)."""

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..core.exceptions import DatabaseError
from ..db.database import get_db_connection
from . import models as binding_models
from . import matcher

log = logging.getLogger(__name__)


def create_code_binding(workspace_id: str, binding: binding_models.CodeBinding) -> binding_models.CodeBinding:
    """Creates a new code binding."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        INSERT INTO code_bindings (item_type, item_id, file_pattern, symbol_pattern,
                                    binding_type, confidence, last_verified_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (
            binding.item_type,
            binding.item_id,
            binding.file_pattern,
            binding.symbol_pattern,
            binding.binding_type,
            binding.confidence,
            binding.last_verified_at,
            binding.created_at,
            binding.updated_at
        ))
        binding.id = cursor.lastrowid
        conn.commit()
        return binding
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to create code binding: {e}")
    finally:
        if cursor:
            cursor.close()


def get_bindings_for_item(
    workspace_id: str,
    item_type: str,
    item_id: int
) -> List[binding_models.CodeBinding]:
    """Retrieves all code bindings for a Engrams entity."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        SELECT id, item_type, item_id, file_pattern, symbol_pattern, binding_type,
               confidence, last_verified_at, created_at, updated_at
        FROM code_bindings
        WHERE item_type = ? AND item_id = ?
        ORDER BY id ASC
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (item_type, item_id))
        rows = cursor.fetchall()
        return [_row_to_binding(row) for row in rows]
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get bindings: {e}")
    finally:
        if cursor:
            cursor.close()


def get_all_bindings(workspace_id: str) -> List[binding_models.CodeBinding]:
    """Retrieves all code bindings."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        SELECT id, item_type, item_id, file_pattern, symbol_pattern, binding_type,
               confidence, last_verified_at, created_at, updated_at
        FROM code_bindings ORDER BY id ASC
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [_row_to_binding(row) for row in rows]
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get all bindings: {e}")
    finally:
        if cursor:
            cursor.close()


def get_bindings_matching_files(
    workspace_id: str,
    file_paths: List[str],
    binding_type_filter: Optional[str] = None
) -> List[binding_models.CodeBinding]:
    """Get all bindings whose file_pattern matches any of the given file paths."""
    all_bindings = get_all_bindings(workspace_id)
    matched: List[binding_models.CodeBinding] = []

    for binding in all_bindings:
        if binding_type_filter and binding.binding_type != binding_type_filter:
            continue
        for fp in file_paths:
            if matcher.match_file_against_pattern(fp, binding.file_pattern):
                matched.append(binding)
                break  # Don't add same binding twice

    return matched


def get_stale_bindings(workspace_id: str, days_stale: int = 30) -> List[binding_models.CodeBinding]:
    """Return bindings that haven't been verified recently or never verified."""
    conn = get_db_connection(workspace_id)
    cursor = None
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_stale)

    sql = """
        SELECT id, item_type, item_id, file_pattern, symbol_pattern, binding_type,
               confidence, last_verified_at, created_at, updated_at
        FROM code_bindings
        WHERE last_verified_at IS NULL OR last_verified_at < ?
        ORDER BY last_verified_at ASC NULLS FIRST
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (cutoff,))
        rows = cursor.fetchall()
        return [_row_to_binding(row) for row in rows]
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to get stale bindings: {e}")
    finally:
        if cursor:
            cursor.close()


def delete_code_binding(workspace_id: str, binding_id: int) -> bool:
    """Deletes a code binding by ID."""
    conn = get_db_connection(workspace_id)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM code_bindings WHERE id = ?", (binding_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to delete binding {binding_id}: {e}")
    finally:
        if cursor:
            cursor.close()


def log_binding_verification(
    workspace_id: str,
    verification: binding_models.CodeBindingVerification
) -> binding_models.CodeBindingVerification:
    """Records a binding verification result."""
    conn = get_db_connection(workspace_id)
    cursor = None
    sql = """
        INSERT INTO code_binding_verifications (binding_id, verification_status, files_matched, verified_at, notes)
        VALUES (?, ?, ?, ?, ?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (
            verification.binding_id,
            verification.verification_status,
            verification.files_matched,
            verification.verified_at,
            verification.notes
        ))
        verification.id = cursor.lastrowid

        # Update last_verified_at on the binding
        cursor.execute(
            "UPDATE code_bindings SET last_verified_at = ?, updated_at = ? WHERE id = ?",
            (verification.verified_at, datetime.now(timezone.utc), verification.binding_id)
        )

        conn.commit()
        return verification
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseError(f"Failed to log verification: {e}")
    finally:
        if cursor:
            cursor.close()


def get_entity_summary(workspace_id: str, item_type: str, item_id: int) -> str:
    """Get a brief summary text for a Engrams entity."""
    table_map = {
        'decision': ('decisions', 'summary'),
        'system_pattern': ('system_patterns', 'name'),
        'progress_entry': ('progress_entries', 'description'),
        'custom_data': ('custom_data', 'key'),
    }
    if item_type not in table_map:
        return f"{item_type} #{item_id}"

    table, field = table_map[item_type]
    conn = get_db_connection(workspace_id)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {field} FROM {table} WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return row[0] if row else f"{item_type} #{item_id}"
    except sqlite3.Error:
        return f"{item_type} #{item_id}"
    finally:
        if cursor:
            cursor.close()


def suggest_bindings_for_item(workspace_id: str, item_type: str, item_id: int) -> List[str]:
    """
    Analyze item text content and suggest likely file patterns.

    Looks for references to paths, modules, or technologies in the item's text.
    """
    table_map = {
        'decision': ('decisions', ['summary', 'rationale', 'implementation_details']),
        'system_pattern': ('system_patterns', ['name', 'description']),
        'progress_entry': ('progress_entries', ['description']),
        'custom_data': ('custom_data', ['value']),
    }
    if item_type not in table_map:
        return []

    table, fields = table_map[item_type]
    conn = get_db_connection(workspace_id)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            return []

        # Gather all text content
        text_parts = []
        for field in fields:
            try:
                val = row[field]
                if val:
                    text_parts.append(str(val))
            except (IndexError, KeyError):
                pass

        full_text = ' '.join(text_parts)

        # Extract potential file patterns
        suggestions = []

        # Look for file path references (e.g., src/auth/login.py, lib/utils.js)
        path_pattern = re.compile(r'(?:^|\s|[`"\'])([a-zA-Z0-9_./\\-]+\.[a-zA-Z]{1,10})(?:\s|[`"\']|$)')
        for match in path_pattern.finditer(full_text):
            path = match.group(1)
            if '/' in path or '\\' in path:
                suggestions.append(path)

        # Look for directory references
        dir_pattern = re.compile(r'(?:^|\s|[`"\'])([a-zA-Z0-9_/\\-]+/)(?:\s|[`"\']|$)')
        for match in dir_pattern.finditer(full_text):
            directory = match.group(1)
            if len(directory) > 3:
                suggestions.append(f"{directory}**/*")

        return list(set(suggestions))

    except sqlite3.Error:
        return []
    finally:
        if cursor:
            cursor.close()


def _row_to_binding(row: sqlite3.Row) -> binding_models.CodeBinding:
    """Convert a database row to a CodeBinding model."""
    return binding_models.CodeBinding(
        id=row['id'],
        item_type=row['item_type'],
        item_id=row['item_id'],
        file_pattern=row['file_pattern'],
        symbol_pattern=row['symbol_pattern'],
        binding_type=row['binding_type'],
        confidence=row['confidence'],
        last_verified_at=row['last_verified_at'],
        created_at=row['created_at'],
        updated_at=row['updated_at']
    )
