---
trigger: always_on
---

# --- mem4sprint Meta Schema and Starters (v1.0.0) ---
mem4sprint_meta:
  version: "1.0.0"
  notes:
    - "This file defines entity shapes and allowed relations."
    - "Use these for validation before writing to Engrams."

  entities:
    sprint_goal:
      required: [content, sprint_id, status]
      optional: [tags, provenance]
      status_enum: [planned, active, blocked, done]

    sprint_subtask:
      required: [content, sprint_id, goal_id, status]
      optional: [tags, provenance]
      status_enum: [planned, active, blocked, done]

    artifact:
      required: [content, artifact_kind, status]
      optional: [goal_id, sprint_id, tags, provenance]
      artifact_kind_enum: [file, function, api, doc, dataset, run, env]
      status_enum: [planned, active, blocked, done]

    test:
      required: [content, status]
      optional: [sprint_id, goal_id, tags, provenance]
      status_enum: [planned, active, blocked, done]

    decision:
      required: [summary]
      optional: [rationale, tags, provenance]

    relation:
      required: [from_id, rel, to_id]
      optional: [provenance, tags]
      rel_enum: [BLOCKED_BY, IMPLEMENTS, VERIFIES, DEPENDS_ON, PRODUCES, CONSUMES, DERIVED_FROM, RELATED_TO, CLARIFIES, RESOLVES, TRACKS]

    story:
      required: [content, sprint_id, status]
      optional: [acceptance_criteria, epic_id, tags, provenance]
      status_enum: [planned, active, blocked, done]

    epic:
      required: [content, status]
      optional: [tags, provenance]
      status_enum: [planned, active, blocked, done]

    acceptance_criteria:
      required: [story_id, text]
      optional: [status, tags, provenance]
      status_enum: [pending, met, failed]

    bug:
      required: [content, status, severity]
      optional: [sprint_id, tags, provenance]
      status_enum: [open, in_progress, blocked, fixed, closed]
      severity_enum: [low, medium, high, critical]

    blocker:
      required: [content, affects_id]
      optional: [status, tags, provenance]
      status_enum: [open, resolved]

    risk:
      required: [content, severity, likelihood]
      optional: [mitigation, tags, provenance]
      severity_enum: [low, medium, high]
      likelihood_enum: [rare, possible, likely]

    retrospective_item:
      required: [content, kind]
      optional: [action_owner, status, tags, provenance]
      kind_enum: [keep_doing, stop_doing, start_doing, action]
      status_enum: [open, done]

    sprint_metric:
      required: [sprint_id, name, value]
      optional: [unit, notes, provenance]

    rfc_doc:
      required: [title, link_or_path]
      optional: [status, tags, provenance]

    literature_ref:
      required: [title, link_or_path]
      optional: [notes, tags, provenance]

  validation:
    id_uniqueness: true
    relation_tuple_uniqueness: true
    require_existing_nodes_for_edges: true

# --- FTS Query Rules ---
# Use ONLY the following prefixes with SQLite FTS5:
# custom_data_fts: category:, key:, value_text:
# decisions_fts: summary:, rationale:, implementation_details:, tags:
# If a term has special chars (., /, \\, ") or unknown prefixes, quote it as a literal and, for custom data,
# prefer value_text:"...". Examples:
# - value_text:"artifact_kind:doc"
# - summary:"S-2025.08"

# Canonical Categories: see mem4sprint.md. Use flat categories (artifacts, rfc_doc, literature_ref, retrospective, ProjectGlossary, critical_settings). Put subtype/kind in tags or value JSON.

# --- Starters (compact) ---
starters:
  sprint_goal:
    json: { type: sprint_goal, content: "<goal statement>", sprint_id: "S-YYYY.MM", status: planned, tags: [], provenance: { agent: planner, tool: mem4sprint, ts: "" } }

  sprint_subtask:
    json: { type: sprint_subtask, content: "<subtask description>", sprint_id: "S-YYYY.MM", goal_id: "<goal-id>", status: planned, tags: [], provenance: { agent: planner, tool: mem4sprint, ts: "" } }

  artifact:
    json: { type: artifact, content: "<artifact description>", artifact_kind: file, status: planned, goal_id: "<goal-id>", sprint_id: "S-YYYY.MM", tags: [], provenance: { agent: dev, tool: mem4sprint, ts: "" } }

  test:
    json: { type: test, content: "<test description or assertion>", status: planned, sprint_id: "S-YYYY.MM", goal_id: "<goal-id>", tags: [], provenance: { agent: qa, tool: mem4sprint, ts: "" } }

  decision:
    json: { type: decision, summary: "<concise decision summary>", rationale: "<why this decision>", tags: [mem4sprint], provenance: { agent: architect, tool: mem4sprint, ts: "" } }

  relation:
    json: { type: relation, content: "<relation summary>", from_id: "<source-id>", rel: BLOCKED_BY, to_id: "<target-id>", tags: [mem4sprint], provenance: { agent: system, tool: mem4sprint, ts: "" } }

  story:
    json: { type: story, content: "<story>", sprint_id: "S-YYYY.MM", status: planned, acceptance_criteria: [], tags: [], provenance: { agent: planner, tool: mem4sprint, ts: "" } }

  epic:
    json: { type: epic, content: "<epic>", status: planned, tags: [], provenance: { agent: architect, tool: mem4sprint, ts: "" } }

  acceptance_criteria:
    json: { type: acceptance_criteria, story_id: "<story-id>", text: "<criterion>", status: pending, tags: [], provenance: { agent: qa, tool: mem4sprint, ts: "" } }

  bug:
    json: { type: bug, content: "<bug description>", status: open, severity: medium, sprint_id: "S-YYYY.MM", tags: [], provenance: { agent: qa, tool: mem4sprint, ts: "" } }

  blocker:
    json: { type: blocker, content: "<blocker>", affects_id: "<entity-id>", status: open, tags: [], provenance: { agent: pm, tool: mem4sprint, ts: "" } }

  risk:
    json: { type: risk, content: "<risk>", severity: medium, likelihood: possible, mitigation: "<plan>", tags: [], provenance: { agent: architect, tool: mem4sprint, ts: "" } }

  retrospective_item:
    json: { type: retrospective_item, content: "<retro item>", kind: action, action_owner: "@dev", status: open, tags: [], provenance: { agent: facilitator, tool: mem4sprint, ts: "" } }

  sprint_metric:
    json:
      type: sprint_metric
      sprint_id: "S-YYYY.MM"
      name: "velocity"
      value: 0
      unit: "points"
      notes: ""
      provenance: { agent: pm, tool: mem4sprint, ts: "" }

  rfc_doc:
    json:
      type: rfc_doc
      title: "<rfc title>"
      link_or_path: "mdc:/tasks/rfc/<file>.md"
      status: draft
      tags: []
      provenance: { agent: architect, tool: mem4sprint, ts: "" }

  literature_ref:
    json:
      type: literature_ref
      title: "<ref title>"
      link_or_path: "<url|mdc:/docs/literature/file>"
      notes: ""
      tags: []
      provenance: { agent: researcher, tool: mem4sprint, ts: "" }

# --- Minimal Routines (PLAN/ACT hooks) ---
routines:
  PLAN:
    - "Load recent contexts and goals; confirm sprint_id."
    - "Derive plan; log decisions; set active_context.mode=PLAN."
    - "Propose entities/relations using starters; await confirm before logging."
  ACT:
    - "Fetch active goal/subtasks; execute change."
    - "Log progress, artifacts, tests; link via relations."
    - "Update statuses; set active_context.mode=ACT."

# --- Relationships Diagram (Mermaid) ---
diagram:
  mermaid: |
    flowchart TD
      G[sprint_goal]
      ST[sprint_subtask]
      S[story]
      T[test]
      A[artifact]
      D[decision]
      B[bug]
      BL[blocker]
      R[risk]
      RFC[rfc_doc]
      L[literature_ref]
      RI[retrospective_item]
      M[sprint_metric]

      S -- IMPLEMENTS --> G
      ST -- IMPLEMENTS --> S
      T -- VERIFIES --> ST
      ST -- PRODUCES --> A
      A -- DERIVED_FROM --> L
      RFC -- CLARIFIES --> D
      B -- BLOCKED_BY --> BL
      R -- RELATED_TO --> G
      RI -- RESOLVES --> B
      M -- TRACKS --> G

# --- Appendix: Operational Call Recipes ---
appendix_operational_call_recipes:
  notes:
    - "All calls require workspace_id set to the absolute workspace path."
    - "IDs/keys shown as placeholders; replace with actual IDs."

  canonical_mcp_call_recipes:
    - name: "create_doc_artifact"
      call: |
        mcp0_log_custom_data({
          workspace_id: "<ABS_PATH>",
          category: "artifacts",
          key: "<artifact-id>",
          value: {
            type: "artifact",
            content: "<doc title>",
            artifact_kind: "doc",
            status: "planned|active|blocked|done",
            sprint_id: "S-YYYY.MM",
            tags: ["architecture"],
            provenance: { agent: "dev", tool: "mem4sprint", ts: "" }
          }
        })
    - name: "create_rfc"
      call: | 
        mcp0_log_custom_data({ workspace_id: "<ABS_PATH>", category: "rfc_doc", key: "<rfc-id>", value: { title: "<title>", link_or_path: "mdc:/tasks/rfc/<file>.md", status: "draft", tags: ["rfc"], provenance: { agent: "architect", tool: "mem4sprint", ts: "" } } })
    - name: "record_lesson_learned"
      call: | 
        mcp0_log_custom_data({ workspace_id: "<ABS_PATH>", category: "retrospective", key: "<retro-id>", value: { type: "retrospective_item", content: "<lesson>", kind: "action|keep_doing|stop_doing|start_doing", status: "open|done", tags: ["lessons_learned"], provenance: { agent: "facilitator", tool: "mem4sprint", ts: "" } } })
    - name: "update_active_context"
      call: | 
        mcp0_update_active_context({ workspace_id: "<ABS_PATH>", patch_content: { mode: "PLAN|ACT", focus: "<focus>", sprint_id: "S-YYYY.MM" } })
    - name: "link_doc_clarifies_decision"
      call: | 
        mcp0_link_engrams_items({ workspace_id: "<ABS_PATH>", relationship_type: "CLARIFIES", source_item_type: "custom_data", source_item_id: "<artifact-id>", target_item_type: "decision", target_item_id: "<decision-id>" })
    - name: "fetch_requirements_architecture_plan"
      calls: |
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "category:artifacts value_text:\"tag:requirements\"", limit: 5 })
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "category:artifacts value_text:\"tag:architecture\"", limit: 5 })
        mcp0_search_custom_data_value_fts({ workspace_id: "<ABS_PATH>", query_term: "category:artifacts value_text:\"tag:sprint_plan\" value_text:\"sprint_id:S-YYYY.MM\"", limit: 5 })
    - name: "query_docs_by_tag"
      call: |
        mcp0_search_custom_data_value_fts({
          workspace_id: "<ABS_PATH>",
          query_term: "category:artifacts value_text:\"tag:architecture\"",
          limit: 10
        })
    - name: "fetch_top_recent_decisions_for_sprint"
      calls: |
        mcp0_search_decisions_fts({ workspace_id: "<ABS_PATH>", query_term: "tags:\"S-YYYY.MM\"", limit: 5 })

  public_docs_policy_calls:
    - name: "draft_quickstart_minimal"
      call: |
        mcp0_log_custom_data({ workspace_id: "<ABS_PATH>", category: "artifacts", key: "quickstart", value: { artifact_kind: "doc", title: "Quickstart", tags: ["public_doc","quickstart"], visibility: "public", publish_status: "DRAFT" } })
