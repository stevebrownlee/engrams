# Engrams — Proposed New Features

> Proposal date: 2026-02-25
> Scope: Features complementary to the existing roadmap (Features 4, 6, 8), targeting token savings and team efficiency

---

## Relationship to Existing Roadmap

The [existing roadmap](FUTURE_FEATURES.md) covers three unimplemented features:

| # | Feature | Focus |
|---|---------|-------|
| 4 | Architectural Drift Detection | Code quality enforcement |
| 6 | Dependency & Impact Graphs | Decision traceability |
| 8 | Template & Pattern Libraries | Cross-project reuse |

The four features proposed below address **orthogonal gaps** — they reduce raw token consumption per session, eliminate redundant context loading, provide observability into context ROI, and prevent coordination waste in multi-agent or multi-developer environments. None conflict with or duplicate the existing roadmap items.

---

## Proposed Feature 9: Context Compaction & Summarization

### Problem

As a project matures, the Engrams database accumulates hundreds of decisions, progress entries, patterns, and custom data items. The existing budgeting system (`src/engrams/budgeting/`) selects the *most relevant* entities via greedy scoring, but every selected entity is injected at **full verbosity** — the original text as authored, no matter how old. For a 6-month project with 200 decisions, even the `compact` format in `estimate_tokens()` still serializes complete `rationale` and `implementation_details` fields.

**Token cost grows linearly with project age while marginal information value decays exponentially.**

### Solution

Introduce a compaction layer that periodically (or on-demand) **summarizes clusters of related, older entities into digest records** — condensed representations that preserve architectural intent while discarding implementation-level verbosity.

### How It Works

1. **Cluster identification** — Group entities by tag overlap, link relationships, and temporal proximity. Entities that share 2+ tags or are linked via `related_to`/`implements` form a natural cluster.
2. **Digest generation** — For each cluster older than a configurable threshold (default: 30 days), produce a single digest entry containing:
   - A one-paragraph summary of the cluster's collective meaning
   - A list of original entity IDs (for drill-down)
   - The union of all tags from constituent entities
   - The most recent `updated_at` timestamp from the cluster
3. **Transparent substitution** — When the budgeting selector runs, it can choose between the original entities and their digest. If the token budget is tight, the digest replaces the full cluster at ~10-20% of the token cost. If budget is generous, originals are still available.
4. **Immutability** — Original entities are never deleted or modified. Digests are a read-optimized overlay.

### Prerequisites Already in Place

- `score_entities()` in [`scorer.py`](../src/engrams/budgeting/scorer.py:96) already computes recency decay with a 30-day half-life — this same signal identifies compaction candidates
- `link_engrams_items` provides the relationship graph needed for cluster identification
- `estimate_tokens()` in [`estimator.py`](../src/engrams/budgeting/estimator.py) provides the token cost comparison between originals and digests
- The `context_links` table already stores typed relationships suitable for cluster boundary detection

### What's Needed

- A `context_digests` table: `(id, workspace_id, digest_text, source_entity_ids JSON, tags JSON, created_at, token_estimate)`
- A cluster identification algorithm (tag overlap + link adjacency + temporal window)
- A summarization strategy — either LLM-generated (via the existing Ollama bridge in `dashboard/ollama_bridge.py`) or extractive (pull the first sentence of each entity's summary)
- Integration with `select_context()` in [`selector.py`](../src/engrams/budgeting/selector.py:54) to offer digest substitution when budget pressure is high
- A `compact_context(workspace_id, older_than_days?, strategy?)` MCP tool

### Suggested MCP Tools

- `compact_context(workspace_id, older_than_days?, cluster_strategy?, summarization_strategy?)` → compaction report with digest IDs and token savings
- `get_digest(workspace_id, digest_id)` → digest content with source entity references
- `expand_digest(workspace_id, digest_id)` → full original entities behind a digest

### Estimated Token Savings

For a project with 150 decisions (avg. 200 tokens each = 30,000 tokens raw):
- Without compaction: budgeting selects ~40 entities → **8,000 tokens**
- With compaction: 100 old decisions compressed to ~10 digests (~50 tokens each) → budgeting can cover the same knowledge in **~3,500 tokens** — a **56% reduction** while preserving the same architectural coverage.

### Value

| Audience | Benefit |
|----------|---------|
| Individual developer | Dramatically lower per-session token cost on mature projects |
| Team | Institutional knowledge stays accessible without paying the full verbosity tax every session |

---

## Proposed Feature 10: Context Usage Analytics & Decay

### Problem

Engrams stores everything an agent logs, but provides **zero observability** into which entities are actually *consumed*. The `get_decisions`, `get_relevant_context`, and `get_context_for_files` tools retrieve entities, but there's no record of:
- Which entities were selected by the budgeting system and actually injected into agent context
- Which entities are retrieved session after session vs. ones that have never been queried
- How token budget is distributed across entity types over time

Without usage data, stale entities accumulate indefinitely, the budgeting scorer has no feedback loop, and teams can't identify which captured knowledge is actually driving value.

### Solution

Add a lightweight **usage tracking and analytics layer** that records retrieval events and exposes aggregate insights.

### How It Works

1. **Retrieval event logging** — Every time `select_context()`, `get_relevant_context()`, or `get_context_for_files()` returns entities, log a retrieval event: `(entity_type, entity_id, timestamp, tool_name, was_selected, token_cost)`. This is an append-only, low-overhead write.
2. **Usage scores** — Periodically compute per-entity usage metrics:
   - `retrieval_count`: total times retrieved in the last N days
   - `selection_rate`: % of retrievals where the entity was actually selected (not just scored)
   - `last_retrieved_at`: most recent retrieval timestamp
3. **Scorer integration** — Add a new scoring factor `usage_frequency` to [`scorer.py`](../src/engrams/budgeting/scorer.py:96) (weight configurable per profile). Entities that are consistently selected get a boost; entities never retrieved get naturally deprioritized.
4. **Analytics dashboard** — Expose aggregate data via the existing dashboard (`src/engrams/dashboard/`):
   - "Top 10 most-used entities this week"
   - "Entities never retrieved (candidates for archival)"
   - "Token budget distribution by entity type"
   - "Context efficiency: tokens spent vs. entities actually used"
5. **Auto-archive suggestions** — Entities with zero retrievals for 60+ days and a low lifecycle score are flagged as archive candidates.

### Prerequisites Already in Place

- `select_context()` in [`selector.py`](../src/engrams/budgeting/selector.py:54) is the single choke point for budgeted context — ideal instrumentation point
- `ScoredEntity` in [`scorer.py`](../src/engrams/budgeting/scorer.py:55) already carries `score_breakdown` — adding `usage_frequency` is a natural extension
- [`profiles.py`](../src/engrams/budgeting/profiles.py:21) weight dictionaries are trivially extensible
- The dashboard (`src/engrams/dashboard/`) already reads from the database — analytics views are a UI addition

### What's Needed

- A `context_retrievals` table: `(id, workspace_id, entity_type, entity_id, tool_name, was_selected, token_cost, timestamp)`
- Instrumentation hooks in `select_context()` and the MCP handler layer
- Aggregate query functions for usage metrics
- A new weight factor `usage_frequency` in scorer profiles
- Dashboard views for analytics (optional but high-value)
- An `archive_entity(workspace_id, entity_type, entity_id)` soft-delete mechanism

### Suggested MCP Tools

- `get_context_analytics(workspace_id, days?, entity_type?)` → usage stats, token distribution, efficiency metrics
- `get_unused_entities(workspace_id, days_unused?, limit?)` → entities with zero retrievals
- `archive_entities(workspace_id, entity_type, entity_ids)` → soft-archive (excluded from scoring but recoverable)
- `restore_archived(workspace_id, entity_type, entity_ids)` → un-archive

### Estimated Token Savings

Usage-informed scoring shifts budget allocation toward entities that agents actually need. Conservative estimate: **15-25% token reduction** from deprioritizing never-used entities that currently occupy budget slots due to high recency or tag overlap scores alone.

### Value

| Audience | Benefit |
|----------|---------|
| Individual developer | Self-tuning context — the system learns what you need over time |
| Team | Identify which team decisions are actually guiding agents vs. sitting unused; data-driven knowledge base hygiene |

---

## Proposed Feature 11: Incremental Context Diffs

### Problem

Every Engrams session starts the same way: the agent calls `get_product_context`, `get_active_context`, `get_decisions`, `get_progress`, and `get_system_patterns` — loading the **entire current state** regardless of how much has changed since the last session. The existing `get_recent_activity_summary` helps, but it returns a *summary* of recent changes, not a structured diff that can be surgically applied.

For a developer working in 30-minute sessions across a day, the context reload pattern looks like:
- Session 1: Load 4,000 tokens of context (cold start)
- Session 2: Load 4,000 tokens again — but only 200 tokens of actual changes
- Session 3: Load 4,000 tokens again — only 150 tokens changed

**~95% of tokens spent on context loading are redundant between consecutive sessions.**

### Solution

Implement a **context checkpoint and diff system** that enables agents to load only what changed since their last known state.

### How It Works

1. **Checkpoints** — After each successful context load, the agent can call `create_context_checkpoint(workspace_id)` which records:
   - A monotonically increasing checkpoint ID (or timestamp)
   - A hash of the current state of `product_context`, `active_context`, and entity counts
   - No full data copy — just the watermark
2. **Diff retrieval** — On subsequent sessions, the agent calls `get_context_diff(workspace_id, since_checkpoint?)` which returns:
   - `product_context_changed: bool` (with the new content only if changed)
   - `active_context_changed: bool` (with the new content only if changed)
   - `new_decisions: [...]` (decisions created after the checkpoint)
   - `updated_decisions: [...]` (decisions modified after the checkpoint)
   - `new_progress: [...]`, `updated_progress: [...]`
   - `new_patterns: [...]`, `updated_patterns: [...]`
   - `new_custom_data: [...]`
   - `deleted_item_ids: [...]`
3. **Compact payload** — The diff response includes only changed entities, not the full database. The agent merges the diff with its prior state.
4. **Fallback** — If no checkpoint exists or the checkpoint is too old (>24h configurable), the system returns a full context load with a `full_reload: true` flag, and the standard budgeting flow applies.

### Prerequisites Already in Place

- `get_item_history()` already tracks versioned changes to `product_context` and `active_context` with timestamps
- All entities have `created_at` and `updated_at` timestamps suitable for diff computation
- `get_recent_activity_summary()` already queries by time window — the diff system extends this with structured output

### What's Needed

- A `context_checkpoints` table: `(id, workspace_id, checkpoint_id, created_at, state_hash, metadata JSON)`
- A diff computation function that queries all entity tables for rows with `created_at > checkpoint.created_at` or `updated_at > checkpoint.created_at`
- Agent-side custom instructions update: teach agents to call `create_context_checkpoint` at session end and `get_context_diff` at session start
- Token estimation for the diff payload so agents can assess whether a diff or full reload is more efficient

### Suggested MCP Tools

- `create_context_checkpoint(workspace_id, metadata?)` → checkpoint_id
- `get_context_diff(workspace_id, since_checkpoint?, since_timestamp?)` → structured diff with changed entities only
- `get_checkpoints(workspace_id, limit?)` → recent checkpoints for reference
- `delete_old_checkpoints(workspace_id, older_than_days?)` → cleanup

### Estimated Token Savings

For a developer doing 5 sessions/day with an average context size of 4,000 tokens:
- Current: 5 × 4,000 = **20,000 tokens/day** on context loading
- With diffs (assuming ~5% change rate per session): 4,000 + 4 × 200 = **4,800 tokens/day** — a **76% reduction** in context loading tokens

### Value

| Audience | Benefit |
|----------|---------|
| Individual developer | Massively reduced context overhead for iterative work sessions; faster agent startup |
| Team | Shared checkpoints enable a lightweight "what changed since I was last here" for async collaboration without the overhead of full session handoffs |

---

## Proposed Feature 12: Work-in-Progress Awareness (Collaborative Conflict Prevention)

### Problem

The existing governance system (`src/engrams/governance/`) detects conflicts **after the fact** — when an individual-scope item contradicts a team-scope rule or decision. But in multi-developer or multi-agent environments, the most expensive conflicts aren't rule violations; they're **two people doing overlapping work simultaneously without knowing it**.

Scenarios:
- Developer A's agent starts refactoring the auth middleware while Developer B's agent is implementing a new auth flow that depends on the current structure
- Two agents modify the same system pattern from different sessions, and the second write silently overwrites the first
- A developer spends 2 hours on an approach that a teammate already explored and abandoned yesterday

The current system has no concept of "who is currently working on what" — `active_context` is per-workspace, not per-developer.

### Solution

Introduce a **lightweight work-in-progress (WIP) registration system** that lets agents declare their current focus area and receive warnings when entering areas with active overlap.

### How It Works

1. **WIP registration** — When an agent begins working on a task, it calls `register_wip(workspace_id, developer_id, focus_area, file_patterns?, tags?, estimated_duration?)`. This creates a time-limited claim (auto-expires after `estimated_duration` or 4 hours default).
   - `focus_area`: free-text description (e.g., "Refactoring auth middleware")
   - `file_patterns`: optional list of file globs the work will touch
   - `tags`: optional tags for semantic matching
2. **Overlap detection** — On registration, the system checks existing active WIPs for:
   - File pattern intersection (glob overlap with other WIPs' `file_patterns`)
   - Tag overlap (shared tags suggest shared concern area)
   - Semantic similarity (if embeddings are available, compare `focus_area` descriptions)
   - Returns overlap warnings with the conflicting WIP details and developer identifiers
3. **Pre-task integration** — The `pre_task_governance_check` in the agent strategy is extended: after checking decisions and governance rules, also call `check_wip_overlaps(workspace_id, focus_area, file_patterns?)` to surface active overlaps *before* work begins.
4. **Auto-expiration** — WIPs expire automatically. No cleanup burden. Developers don't need to remember to "close" their work session.
5. **Activity feed** — `get_active_wips(workspace_id)` returns all current work-in-progress registrations for the team, providing a real-time "who's working on what" view.

### Prerequisites Already in Place

- `active_context` in [`database.py`](../src/engrams/db/database.py) stores current focus — WIP extends this concept to be multi-tenant and time-bounded
- The governance `conflict_detector.py` pattern of tag overlap checking directly applies to WIP overlap detection
- The bindings `matcher.py` glob matching can detect file pattern intersections between WIPs
- Semantic search infrastructure (`embedding_service.py`, `vector_store_service.py`) can compare focus area descriptions

### What's Needed

- A `work_in_progress` table: `(id, workspace_id, developer_id, focus_area, file_patterns JSON, tags JSON, started_at, expires_at, status)`
- Overlap detection logic combining file glob intersection, tag overlap, and optional semantic similarity
- Integration with the pre-task governance check flow
- Auto-expiration via timestamp comparison (no background process needed — check on read)
- Dashboard view showing active WIPs per workspace

### Suggested MCP Tools

- `register_wip(workspace_id, developer_id, focus_area, file_patterns?, tags?, estimated_duration_minutes?)` → WIP ID + any detected overlaps
- `check_wip_overlaps(workspace_id, focus_area, file_patterns?, tags?)` → overlap report without registering
- `get_active_wips(workspace_id, developer_id?)` → list of current WIP registrations
- `complete_wip(workspace_id, wip_id, outcome?)` → explicitly mark WIP as done (optional; auto-expiration handles neglected ones)
- `extend_wip(workspace_id, wip_id, additional_minutes)` → extend expiration

### Estimated Efficiency Gains

In a 4-person team doing 3 overlapping-risk tasks/day:
- Without WIP awareness: ~2-3 overlap incidents/week, each costing 1-4 hours of rework or merge resolution
- With WIP awareness: overlaps detected before work begins; estimated **60-80% reduction in wasted rework hours**

### Value

| Audience | Benefit |
|----------|---------|
| Individual developer | Know before you start whether someone else is in the same area; avoid wasted effort |
| Team | Real-time visibility into parallel workstreams; governance shifts from reactive conflict detection to proactive collision avoidance |

---

## Implementation Priority Suggestion (New Features Only)

1. **Feature 11 (Incremental Context Diffs)** — Lowest implementation complexity (timestamp queries on existing tables), highest immediate token savings (~76% for iterative sessions), zero dependency on external services.
2. **Feature 10 (Usage Analytics & Decay)** — Medium complexity (new table + instrumentation), creates a self-improving feedback loop that compounds savings over time. Directly enhances the existing budgeting system.
3. **Feature 9 (Context Compaction)** — Higher complexity (clustering + summarization), but addresses the fundamental scaling problem of long-lived projects. Can use extractive summarization initially (no LLM dependency) and upgrade to LLM-generated digests later.
4. **Feature 12 (WIP Awareness)** — Most valuable for **teams** specifically. Lower priority for solo developers. Implementation is straightforward but value depends on adoption across team members' agent configurations.

## Combined Impact Estimate

| Feature | Token Savings | Efficiency Gain | Primary Audience |
|---------|--------------|-----------------|-----------------|
| 9 — Compaction | ~56% on mature projects | Faster context loads | Individual + Team |
| 10 — Analytics | ~15-25% via deprioritization | Knowledge base hygiene | Team |
| 11 — Diffs | ~76% on consecutive sessions | Faster agent startup | Individual |
| 12 — WIP Awareness | Indirect (avoids rework) | 60-80% less overlap rework | Team |
