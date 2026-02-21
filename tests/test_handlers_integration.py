import os
import json

from engrams.db import models
from engrams.handlers import mcp_handlers as H


def as_dict(obj):
    if isinstance(obj, dict):
        return obj
    try:
        return obj.model_dump(mode="json")
    except Exception:
        return json.loads(json.dumps(obj, default=str))


def test_handlers_integration_smoke():
    workspace_id = os.getcwd()

    # Product Context
    upd_pc = H.handle_update_product_context(
        models.UpdateContextArgs(workspace_id=workspace_id, content={"goal": "Integration test run"})
    )
    assert as_dict(upd_pc).get("status") == "success"
    pc = H.handle_get_product_context(models.GetContextArgs(workspace_id=workspace_id))
    assert isinstance(pc, dict)
    assert "goal" in pc

    # Active Context
    upd_ac = H.handle_update_active_context(
        models.UpdateContextArgs(workspace_id=workspace_id, content={"focus": "Integration test"})
    )
    assert as_dict(upd_ac).get("status") == "success"
    ac = H.handle_get_active_context(models.GetContextArgs(workspace_id=workspace_id))
    assert isinstance(ac, dict)

    # Decision
    dec = H.handle_log_decision(
        models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary="Integration test decision",
            rationale="Automated handler-level test",
            tags=["integration", "test"],
        )
    )
    dec_d = as_dict(dec)
    assert "id" in dec_d and isinstance(dec_d["id"], int)

    # Progress
    prog = H.handle_log_progress(
        models.LogProgressArgs(
            workspace_id=workspace_id,
            status="IN_PROGRESS",
            description="Integration test progress entry",
        )
    )
    prog_d = as_dict(prog)
    assert "id" in prog_d and isinstance(prog_d["id"], int)

    # Link decision → progress
    link = H.handle_link_engrams_items(
        models.LinkEngramsItemsArgs(
            workspace_id=workspace_id,
            source_item_type="decision",
            source_item_id=str(dec_d["id"]),
            target_item_type="progress_entry",
            target_item_id=str(prog_d["id"]),
            relationship_type="tested_by",
        )
    )
    link_d = as_dict(link)
    assert "id" in link_d

    links = H.handle_get_linked_items(
        models.GetLinkedItemsArgs(
            workspace_id=workspace_id, item_type="decision", item_id=str(dec_d["id"])
        )
    )
    assert isinstance(links, list)

    # System Pattern
    patt = H.handle_log_system_pattern(
        models.LogSystemPatternArgs(
            workspace_id=workspace_id,
            name="Integration Pattern",
            description="Pattern created during integration test",
            tags=["integration"],
        )
    )
    patt_d = as_dict(patt)
    assert "id" in patt_d

    patterns = H.handle_get_system_patterns(
        models.GetSystemPatternsArgs(workspace_id=workspace_id, limit="1")
    )
    assert isinstance(patterns, list)

    # Custom Data
    H.handle_log_custom_data(
        models.LogCustomDataArgs(
            workspace_id=workspace_id,
            category="TestScript",
            key="IntegrationRun",
            value={"status": "success"},
        )
    )
    cdata = H.handle_get_custom_data(
        models.GetCustomDataArgs(workspace_id=workspace_id, category="TestScript")
    )
    assert isinstance(cdata, list)

    # FTS
    fts = H.handle_search_decisions_fts(
        models.SearchDecisionsArgs(
            workspace_id=workspace_id, query_term="integration", limit="2"
        )
    )
    assert isinstance(fts, list)

    # Glossary FTS (may be empty)
    glossary = H.handle_search_project_glossary_fts(
        models.SearchProjectGlossaryArgs(
            workspace_id=workspace_id, query_term="integration", limit="2"
        )
    )
    assert isinstance(glossary, list)

    # Recent Activity Summary (coercion of numeric-like strings)
    ras = H.handle_get_recent_activity_summary(
        models.GetRecentActivitySummaryArgs(
            workspace_id=workspace_id, hours_ago="24", limit_per_type="3"
        )
    )
    assert isinstance(ras, dict)
    for key in [
        "recent_decisions",
        "recent_progress_entries",
        "recent_product_context_updates",
        "recent_active_context_updates",
        "recent_links_created",
        "recent_system_patterns",
        "notes",
    ]:
        assert key in ras

    # Export
    export = H.handle_export_engrams_to_markdown(
        models.ExportEngramsToMarkdownArgs(workspace_id=workspace_id)
    )
    export_d = as_dict(export)
    assert export_d.get("status") == "success"
    assert "engrams_export" in export_d.get("message", "")