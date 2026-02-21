"""Read-only SQLite access to a Engrams workspace database (Feature 5)."""

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class EngramsReader:
    """Read-only access to a Engrams workspace database."""

    def __init__(self, workspace_path: str):
        db_path = os.path.join(workspace_path, "engrams", "context.db")
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Engrams database not found at: {db_path}")
        self.db_path = db_path
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cursor.fetchone() is not None

    # --- Overview / Stats ---

    def get_overview(self) -> Dict[str, Any]:
        """Get project overview stats."""
        cursor = self.conn.cursor()
        stats: Dict[str, Any] = {}

        # Product context
        try:
            cursor.execute(
                "SELECT content FROM product_context WHERE id = 1"
            )
            row = cursor.fetchone()
            if row:
                stats["product_context"] = {
                    "content": json.loads(row["content"]) if row["content"] else {},
                }
        except Exception:
            stats["product_context"] = None

        # Counts
        for table in [
            "decisions",
            "system_patterns",
            "progress_entries",
            "custom_data",
        ]:
            try:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")  # noqa: S608
                stats[f"{table}_count"] = cursor.fetchone()["cnt"]
            except Exception:
                stats[f"{table}_count"] = 0

        # Links count
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM engrams_item_links")
            stats["links_count"] = cursor.fetchone()["cnt"]
        except Exception:
            stats["links_count"] = 0

        # Feature availability
        stats["features"] = {
            "governance": self._table_exists("context_scopes"),
            "bindings": self._table_exists("code_bindings"),
        }

        return stats

    # --- Product/Active Context ---

    def get_product_context(self) -> Dict[str, Any]:
        """Get the product context entry."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT content FROM product_context WHERE id = 1"
        )
        row = cursor.fetchone()
        if row:
            return {
                "content": json.loads(row["content"]) if row["content"] else {},
            }
        return {"content": {}}

    def get_active_context(self) -> Dict[str, Any]:
        """Get the active context entry."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT content FROM active_context WHERE id = 1"
        )
        row = cursor.fetchone()
        if row:
            return {
                "content": json.loads(row["content"]) if row["content"] else {},
            }
        return {"content": {}}

    # --- Decisions ---

    def get_decisions(
        self,
        tags: Optional[List[str]] = None,
        search: Optional[str] = None,
        scope_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Get decisions with optional filtering.

        Args:
            tags: Optional list of tags to filter by (currently unused, reserved).
            search: Optional FTS or substring search query.
            scope_id: Optional scope ID filter (Feature 1).
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of decision dicts.
        """
        cursor = self.conn.cursor()
        query = "SELECT * FROM decisions"
        conditions: List[str] = []
        params: List[Any] = []

        if scope_id is not None and self._table_exists("context_scopes"):
            conditions.append("scope_id = ?")
            params.append(scope_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)

        # FTS search filter
        if search:
            try:
                fts_cursor = self.conn.cursor()
                fts_cursor.execute(
                    "SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH ?",
                    (search,),
                )
                fts_ids = {r["rowid"] for r in fts_cursor.fetchall()}
                results = [r for r in results if r.get("id") in fts_ids]
            except Exception:
                # FTS may not be available; filter in Python as fallback
                search_lower = search.lower()
                results = [
                    r
                    for r in results
                    if search_lower in (r.get("summary", "") or "").lower()
                    or search_lower in (r.get("rationale", "") or "").lower()
                ]

        return results

    def get_decision_by_id(self, decision_id: int) -> Optional[Dict]:
        """Get a single decision by ID with linked items and bindings."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # Get linked items
            d["linked_items"] = self._get_linked_items("decision", decision_id)
            # Get code bindings (Feature 2)
            if self._table_exists("code_bindings"):
                d["code_bindings"] = self._get_bindings("decision", decision_id)
            return d
        return None

    # --- Patterns ---

    def get_patterns(
        self,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Get system patterns with optional filtering.

        Args:
            tags: Optional list of tags to filter by (currently unused, reserved).
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of pattern dicts.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM system_patterns ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    def get_pattern_by_id(self, pattern_id: int) -> Optional[Dict]:
        """Get a single system pattern by ID with linked items and bindings."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM system_patterns WHERE id = ?", (pattern_id,)
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            d["linked_items"] = self._get_linked_items("system_pattern", pattern_id)
            if self._table_exists("code_bindings"):
                d["code_bindings"] = self._get_bindings("system_pattern", pattern_id)
            return d
        return None

    # --- Progress ---

    def get_progress(
        self,
        status: Optional[str] = None,
        parent_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Get progress entries with optional filtering.

        Args:
            status: Optional status filter (e.g. 'in_progress', 'done').
            parent_id: Optional parent progress entry ID filter.
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of progress entry dicts.
        """
        cursor = self.conn.cursor()
        query = "SELECT * FROM progress_entries"
        conditions: List[str] = []
        params: List[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # --- Custom Data ---

    def get_custom_data(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Get custom data entries with optional filtering.

        Args:
            category: Optional category filter.
            search: Optional substring search across value, key, category.
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of custom data dicts.
        """
        cursor = self.conn.cursor()
        query = "SELECT * FROM custom_data"
        conditions: List[str] = []
        params: List[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY category, key LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)

        if search:
            search_lower = search.lower()
            results = [
                r
                for r in results
                if search_lower in str(r.get("value", "")).lower()
                or search_lower in (r.get("key", "") or "").lower()
                or search_lower in (r.get("category", "") or "").lower()
            ]

        return results

    def get_custom_data_entry(self, category: str, key: str) -> Optional[Dict]:
        """Get a single custom data entry by category and key."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM custom_data WHERE category = ? AND key = ?",
            (category, key),
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d
        return None

    def get_categories(self) -> List[str]:
        """Get all custom data categories."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT DISTINCT category FROM custom_data ORDER BY category"
        )
        return [row["category"] for row in cursor.fetchall()]

    # --- Knowledge Graph ---

    def get_graph_data(
        self, type_filter: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Build a knowledge graph structure for D3.js consumption.

        Returns:
            Dict with 'nodes' (list) and 'edges' (list) keys.
        """
        cursor = self.conn.cursor()
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        # Collect nodes from each entity type
        entity_tables: Dict[str, str] = {
            "decision": "decisions",
            "system_pattern": "system_patterns",
            "progress": "progress_entries",
            "custom_data": "custom_data",
        }

        label_queries: Dict[str, str] = {
            "decision": "SELECT id, summary as label FROM decisions",
            "system_pattern": "SELECT id, name as label FROM system_patterns",
            "progress": "SELECT id, description as label FROM progress_entries",
            "custom_data": "SELECT id, category || ':' || key as label FROM custom_data",
        }

        for entity_type, table in entity_tables.items():
            if type_filter and entity_type not in type_filter:
                continue
            try:
                cursor.execute(label_queries[entity_type])
                for row in cursor.fetchall():
                    nodes.append(
                        {
                            "id": f"{entity_type}:{row['id']}",
                            "type": entity_type,
                            "label": (row["label"] or "")[:60],
                        }
                    )
            except Exception as e:
                log.warning("Error fetching nodes for %s: %s", entity_type, e)

        # Collect edges from item links
        node_ids = {n["id"] for n in nodes}
        try:
            cursor.execute("SELECT * FROM engrams_item_links")
            for row in cursor.fetchall():
                source = f"{row['source_item_type']}:{row['source_item_id']}"
                target = f"{row['target_item_type']}:{row['target_item_id']}"
                # Only include edges where both nodes exist in the current set
                if source in node_ids and target in node_ids:
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "relationship": row["relationship_type"],
                        }
                    )
        except Exception as e:
            log.warning("Error fetching edges: %s", e)

        return {"nodes": nodes, "edges": edges}

    # --- Global Search ---

    def global_search(self, query: str, limit: int = 50) -> List[Dict]:
        """Search across all FTS5 indexes, return unified results."""
        results: List[Dict] = []

        # Search decisions via FTS
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """SELECT d.id, d.summary, d.rationale, d.tags
                   FROM decisions_fts f
                   JOIN decisions d ON f.rowid = d.id
                   WHERE decisions_fts MATCH ?
                   LIMIT ?""",
                (query, limit),
            )
            for row in cursor.fetchall():
                results.append(
                    {
                        "type": "decision",
                        "id": row["id"],
                        "title": row["summary"],
                        "snippet": (row["rationale"] or "")[:200],
                    }
                )
        except Exception:
            pass

        # Search custom data via FTS
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """SELECT cd.id, cd.category, cd.key, cd.value
                   FROM custom_data_fts f
                   JOIN custom_data cd ON f.rowid = cd.id
                   WHERE custom_data_fts MATCH ?
                   LIMIT ?""",
                (query, limit),
            )
            for row in cursor.fetchall():
                results.append(
                    {
                        "type": "custom_data",
                        "id": row["id"],
                        "title": f"{row['category']}:{row['key']}",
                        "snippet": str(row["value"] or "")[:200],
                    }
                )
        except Exception:
            pass

        return results[:limit]

    # --- Governance (Feature 1) ---

    def get_scopes(self) -> List[Dict]:
        """Get all context scopes. Returns empty list if Feature 1 is absent."""
        if not self._table_exists("context_scopes"):
            return []
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM context_scopes ORDER BY scope_type, scope_name"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_governance_rules(self) -> List[Dict]:
        """Get active governance rules. Returns empty list if Feature 1 is absent."""
        if not self._table_exists("governance_rules"):
            return []
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM governance_rules WHERE is_active = 1")
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("rule_definition"):
                try:
                    d["rule_definition"] = json.loads(d["rule_definition"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    def get_scope_amendments(self, status: Optional[str] = None) -> List[Dict]:
        """Get scope amendments. Returns empty list if Feature 1 is absent."""
        if not self._table_exists("scope_amendments"):
            return []
        cursor = self.conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM scope_amendments WHERE status = ?", (status,)
            )
        else:
            cursor.execute("SELECT * FROM scope_amendments")
        return [dict(row) for row in cursor.fetchall()]

    # --- Code Bindings (Feature 2) ---

    def get_bindings_overview(self) -> List[Dict]:
        """Get all code bindings. Returns empty list if Feature 2 is absent."""
        if not self._table_exists("code_bindings"):
            return []
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM code_bindings ORDER BY item_type, item_id")
        return [dict(row) for row in cursor.fetchall()]

    # --- Helpers ---

    def _get_linked_items(self, item_type: str, item_id: int) -> List[Dict]:
        """Get linked items for a given entity (both directions)."""
        cursor = self.conn.cursor()
        links: List[Dict] = []
        try:
            cursor.execute(
                """SELECT * FROM engrams_item_links
                   WHERE (source_item_type = ? AND source_item_id = ?)
                      OR (target_item_type = ? AND target_item_id = ?)""",
                (item_type, item_id, item_type, item_id),
            )
            for row in cursor.fetchall():
                links.append(dict(row))
        except Exception:
            pass
        return links

    def _get_bindings(self, item_type: str, item_id: int) -> List[Dict]:
        """Get code bindings for a given entity."""
        cursor = self.conn.cursor()
        bindings: List[Dict] = []
        try:
            cursor.execute(
                "SELECT * FROM code_bindings WHERE item_type = ? AND item_id = ?",
                (item_type, item_id),
            )
            for row in cursor.fetchall():
                bindings.append(dict(row))
        except Exception:
            pass
        return bindings

    # --- Recent Activity ---

    def get_recent_activity(self, limit: int = 20) -> List[Dict]:
        """Get recent activity across all entity types, sorted by updated_at."""
        activity: List[Dict] = []

        tables = [
            ("decision", "decisions", "summary"),
            ("system_pattern", "system_patterns", "name"),
            ("progress", "progress_entries", "description"),
        ]

        for entity_type, table, label_col in tables:
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    f"SELECT id, {label_col} as label, timestamp FROM {table} "  # noqa: S608
                    "ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
                for row in cursor.fetchall():
                    activity.append(
                        {
                            "type": entity_type,
                            "id": row["id"],
                            "label": row["label"],
                            "timestamp": row["timestamp"],
                        }
                    )
            except Exception:
                pass

        # Sort by timestamp descending across all types
        activity.sort(key=lambda x: x.get("timestamp", "") or "", reverse=True)
        return activity[:limit]
