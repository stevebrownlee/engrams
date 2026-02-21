---
trigger: always_on
---

mem4sprint_strategy:
  notes:
    - "Prefix every response with [CONPORT_ACTIVE] or [CONPORT_INACTIVE]."
    - "Always include workspace_id (absolute path) in Engrams tool calls."
    - "Source of truth: Engrams DB for operational memory; this repo's rule files drive behavior."
    - "Self-contained: this file and mem4sprint.schema_and_templates.md are authoritative. Do NOT assume external strategy files."

  initialization:
    agent_action_plan:
      - step: 1
        do: "Determine ACTUAL_WORKSPACE_ID."
      - step: 2
        do: "List ACTUAL_WORKSPACE_ID + '/engrams/' to check 'context.db'."
      - step: 3
        branch:
          - if: "context.db exists"
            then:
              - "get_product_context → store"
              - "get_active_context → store"
              - "get_decisions(limit:5) → store"
              - "get_progress(limit:5) → store"
              - "get_system_patterns(limit:5) → store"
              - "get_custom_data(category:'critical_settings') → store"
              - "get_custom_data(category:'ProjectGlossary') → store"
              - "Set status [CONPORT_ACTIVE]. Offer: review recent, continue, or new task."
          - elif: "context.db missing"
            then:
              - "Tell user no DB found. Ask to initialize now."
              - "If yes and 'projectBrief.md' exists: read then update_product_context(content:{initial_product_brief: ...})."
              - "Proceed to load sequence above."
          - else: "tool failure"
            then:
              - "Tell user Engrams unavailable. Set [CONPORT_INACTIVE]."

  general:
    - "Proactive logging: propose decisions/progress/context updates; ask before logging."
    - "Semantic search: use when keywords are insufficient; state why."
    - "Error handling: on tool errors, log_custom_data(category:'ErrorLogs', key:'<ts>_error', value: details)."
    - "DB-only operational memory; on-demand export to markdown for review."

  # FTS Query Rules (SQLite FTS5)
  # - custom_data_fts: use only category:, key:, value_text:
  # - decisions_fts: use only summary:, rationale:, implementation_details:, tags:
  # - If a term has special chars (., /, \\, ") or contains unknown prefixes, quote it as a literal.
  #   Prefer value_text:"..." for custom data literals. Examples:
  #   - value_text:"artifact_kind:doc"
  #   - summary:"S-2025.08"

  modes:
    - PLAN:
        checklist:
          - "Load recent contexts and relevant entities (goals, decisions)."
          - "Synthesize approach; ask clarifying questions if uncertain."
          - "Log decisions; set/patch active_context (focus, mode=PLAN)."
    - ACT:
        checklist:
          - "Retrieve current goal/subtasks."
          - "Execute minimal change; document as progress."
          - "Link artifacts/tests/decisions; set/patch active_context (mode=ACT)."

  entity_operations:
    add_entity:
      description: "Create sprint entities in Engrams (DB-only)."
      steps:
        - "Use log_custom_data for entity types: sprint_goal, sprint_subtask, artifact, test."
        - "Use log_decision for decision items when appropriate (summary/rationale)."
        - "Include provenance (agent, tool, run_id, ts) when available."
    add_relation:
      description: "Link two items with a typed relation."
      steps:
        - "Use link_engrams_items(source_item_type, source_item_id, target_item_type, target_item_id, relationship_type)."
        - "Allowed types: BLOCKED_BY, IMPLEMENTS, VERIFIES, DEPENDS_ON, PRODUCES, CONSUMES, DERIVED_FROM."
    update_status:
      description: "Update status fields for sprint_goal/subtask/test/artifact."
      steps:
        - "Patch the underlying custom_data value or create a progress_entry reflecting the change."

  search_and_navigation:
    quick_patterns:
      - name: "blocked_tests"
        do: "search_custom_data_value_fts(query_term:'value_text:\"status:blocked\" value_text:\"type:test\"') → summarize"
      - name: "two_hop_blocked_subtasks"
        do: "Find tests by term/sprint → get_linked_items(rel=BLOCKED_BY, linked to tests) → hydrate source subtasks → list"

  export_review:
    - "Use export_engrams_to_markdown(output_path:'engrams_export/<YYYY-MM-DD_HH-mm>/') on demand."
    - "Never treat exported files as source of truth; they're snapshots for review."

  error_handling:
    - "Capture failure details in ErrorLogs; surface concise remediation to user."

  sprint_docs_coverage:
    mapping:
      - { name: "architecture.md", represent_as: "artifact (doc)", tags: [architecture] }
      - { name: "product_requirement_docs.md", represent_as: "artifact (doc)", tags: [requirements] }
      - { name: "sprint_plan.md", represent_as: "artifact (doc)", tags: [sprint_plan] }
      - { name: "RFCs", represent_as: "rfc_doc", tags: [rfc] }
      - { name: "Literature", represent_as: "literature_ref", tags: [literature] }

  canonical_mcp_call_recipes: "See Appendix: Operational Call Recipes in mem4sprint.schema_and_templates.md"

  engrams_sync_routine:
    trigger: "^(Sync Engrams|Engrams Sync)$"
    user_ack: "[CONPORT_SYNCING]"
    do:
      - "Stop current activity; send [CONPORT_SYNCING]."
      - "Review chat for new info: decisions, progress, context changes, links."
      - "Log/Update accordingly: log_decision, log_progress/update_progress, update_active_context/product_context, log_system_pattern, link_engrams_items, batch_log_items."
      - "Optionally get_recent_activity_summary to confirm."
      - "Tell user sync complete; resume or await next task."

  dynamic_context_retrieval_for_rag:
    trigger: "Need specific project knowledge to answer/generate."
    steps:
      - "Analyze query: entities/terms/item types needed."
      - "Retrieve narrowly: search_decisions_fts, search_custom_data_value_fts, search_project_glossary_fts."
      - "If specific items/IDs implied: get_custom_data/get_decisions/get_system_patterns/get_progress."
      - "Fallback if sparse: get_product_context or get_active_context (be brief)."
      - "Optionally 1-hop expand: get_linked_items for top candidates."
      - "Sift + synthesize concise context; attribute sources briefly."
    note: "Prefer semantic_search_engrams for conceptual queries when keywords are weak. Keep retrieved context small and targeted."

  proactive_knowledge_graph_linking:
    trigger: "Conversation implies relationships between Engrams items."
    steps:
      - "Detect strong candidates (e.g., decision → progress implements; test verifies subtask)."
      - "Propose link with brief rationale; ask for confirmation + relationship type."
      - "On confirm: call link_engrams_items with agreed relationship and optional description."
      - "Common relationships: IMPLEMENTS, BLOCKED_BY, VERIFIES, DEPENDS_ON, RELATED_TO, CLARIFIES, RESOLVES, DERIVED_FROM, TRACKS."

  context_budget_checklist:
    keep_in_ai_context_only:
      - "active_context: { mode, sprint_id, focus }"
      - "Current goal/story/subtasks: IDs + 1-line summaries"
      - "Top blockers (<=3) with owners"
      - "Latest decisions (<=3) relevant to task"
      - "IDs/tags to fetch key docs (requirements, architecture, sprint_plan)"
    fetch_from_engrams:
      - "All docs (artifact_kind: doc), RFCs, literature refs"
      - "Full decision log, progress history, metrics"
      - "Broader backlog stories beyond those active"

  turn_start_fetch_recipes:
    - name: "fetch_requirements_architecture_plan"
      calls: |
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "value_text:\"artifact_kind:doc\" value_text:\"tag:requirements\"", limit: 5 })
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "value_text:\"artifact_kind:doc\" value_text:\"tag:architecture\"", limit: 5 })
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "value_text:\"artifact_kind:doc\" value_text:\"tag:sprint_plan\" value_text:\"sprint_id:S-YYYY.MM\"", limit: 5 })
    - name: "fetch_top_recent_decisions_for_sprint"
      calls: |
        mcp0_search_decisions_fts({ workspace_id: "<ABS_PATH>", query_term: "tags:\"S-YYYY.MM\"", limit: 5 })

  artifact_versioning_policy:
    minor_edits:
      - "Update in place (same category/key), e.g., key: 'architecture'"
      - "Optionally log a small decision if it impacts engineering behavior"
    major_revisions:
      - "Create a new versioned key, e.g., 'architecture@v2' or 'architecture@2025-08-10'"
      - "Include fields in value: { version, revised_at, sprint_id, rationale }"
      - "Link new→old with link_engrams_items: relationship RELATED_TO, description: 'supersedes <old-key>' (or DERIVED_FROM if adopted)"
      - "Log a Decision summarizing the change; link Decision ↔ doc via CLARIFIES/RELATED_TO"
    snapshots:
      - "Use export_engrams_to_markdown for point-in-time snapshots (releases, retros, audits)"
    deletion:
      - "Avoid deleting historical docs; only delete mistakes/duplicates via delete_custom_data"

  public_docs_policy:
    purpose: "Define when/how to produce user-facing docs for the project website while keeping Engrams as the source of truth."
    triggers:
      - "Initial public release or major new feature"
      - "API/CLI reaches stability (versioned)"
      - "Architecture shifts affecting contributors/users"
      - "Retro outcome requiring improved onboarding/ops docs"
    doc_types_and_tags:
      - "README, Quickstart, Architecture (public), Technical Guide, API/CLI Reference, How-To, FAQ, Contributing → tag with public_doc + specific type tag"
    production_flow:
      - "Draft as Engrams artifact: category 'artifacts', key '<doc-key>', value includes { title, audience, visibility: 'public', publish_status, publish_targets, slug, version, revised_at }"
      - "Link to internal sources (requirements/architecture/decisions/progress/tests) using link_engrams_items"
      - "Gatekeeping: set publish_status = DRAFT → REVIEWED → PUBLISHED (store reviewer/date in value)"
      - "On publish: export_engrams_to_markdown to a website content path; actual site build/deploy handled outside Engrams"
      - "Record website URL in value (e.g., value.website_url) and keep Engrams as canonical source"
    retrieval_queries:
      - "mcp0_search_custom_data_value_fts(query_term: 'category:artifacts value_text:\"tag:public_doc\" value_text:\"publish_status:PUBLISHED\"')"
    canonical_mcp_calls: "See Appendix: Operational Call Recipes in mem4sprint.schema_and_templates.md"

  tools_reference: "Use get_engrams_schema to retrieve the authoritative tool list."
