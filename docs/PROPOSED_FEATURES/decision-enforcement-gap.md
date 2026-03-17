# Decision Enforcement Gap — Architecture Options

## Problem Statement

Accepted team decisions in `.engrams/decisions/` are **data records only**. They
are not wired into the formal governance enforcement engine
(`governance_rules` + `conflict_detector.py`). This means:

1. The conflict detector at `src/engrams/governance/conflict_detector.py:53`
   **skips all items with no `scope_id`** — and no scopes are created by default.
2. Even when scopes exist, the conflict detector checks `governance_rules` table
   entries — **not accepted decisions**.
3. The only "enforcement" of decisions is prompt-based: the
   `BUILTIN_STRATEGY["governance"]` text in `mcp_handlers.py` tells the AI agent
   to check decisions before mutations. This is advisory, not enforced.

### What happened

A user asked to "switch from SQLite to PostgreSQL." The AI agent skipped the
governance check entirely, read 2000+ lines of source code planning the
migration, and only discovered the blocking Decision #002 ("Use SQLite as the
primary database via SQLAlchemy ORM") after the user intervened. The accepted
decision had no enforcement mechanism.

---

## Options

### Option A — Decision-Aware Conflict Detector (Recommended)

**What changes:** Modify `conflict_detector.check_conflicts()` to also scan
accepted decisions for semantic overlap, independent of scopes/rules.

**How it works:**

1. Add a new function `check_decision_conflicts(workspace_id, proposed_action)`
   to `conflict_detector.py`
2. It reads all accepted decisions (from DB or `.engrams/decisions/`)
3. It checks tag overlap and keyword matching between the proposed action and
   existing decisions
4. Returns a `ConflictCheckResult` with any blocking decisions cited
5. Wire this into `_apply_governance_checks()` in `mcp_handlers.py` so it runs
   **before every write**, regardless of scope assignment

**Scope of change:**
- `src/engrams/governance/conflict_detector.py` — add `check_decision_conflicts()`
- `src/engrams/handlers/mcp_handlers.py` — modify `_apply_governance_checks()`
  to call it unconditionally (remove the `scope_id is None → skip` gate for
  decision-level checks)
- No schema changes needed

**Tradeoffs:**
- ✅ Catches conflicts at the code level, not just prompt level
- ✅ Works without any governance setup (scopes/rules)
- ✅ Minimal migration — extends existing infrastructure
- ⚠️ Tag/keyword matching has false positives — a decision tagged `database`
  would flag any new database-related decision, not just contradictions
- ⚠️ Still post-write (logs the item, then flags it) unless refactored to
  pre-write

---

### Option B — Pre-Mutation Governance Gate Tool

**What changes:** Add a new MCP tool `check_planned_action` that agents call
**before** making changes, and modify the strategy instructions to make it
mandatory.

**How it works:**

1. New tool: `check_planned_action(workspace_id, task_description, tags=[])`
2. The tool runs semantic search (via existing `semantic_search_engrams`
   infrastructure) and tag-based matching against all accepted decisions
3. Returns `{blocked: bool, conflicts: [...], proceed: bool}`
4. Update `BUILTIN_STRATEGY["governance"]` to instruct: "You MUST call
   `check_planned_action` before any workspace mutation. If blocked=true, STOP."
5. Optionally: the server tracks whether `check_planned_action` was called in
   the current session, and if a write tool is called without a prior check,
   includes a warning in the response

**Scope of change:**
- `src/engrams/governance/conflict_detector.py` — add
  `check_planned_action()` logic
- `src/engrams/handlers/mcp_handlers.py` — register new tool, add session
  tracking
- `src/engrams/main.py` — register the new MCP tool endpoint
- `BUILTIN_STRATEGY["governance"]` — update instructions

**Tradeoffs:**
- ✅ Pre-mutation (catches conflicts before any write happens)
- ✅ Uses semantic search, so it can catch conceptual contradictions (not just
  tag overlap)
- ✅ Gives agents a clear, explicit tool to call
- ⚠️ Still depends on AI voluntarily calling the tool (unless combined with
  Option C)
- ⚠️ Adds a new tool to the MCP surface area

---

### Option C — Server-Side Pre-Write Enforcement

**What changes:** Inject a mandatory governance check **inside** every write
handler, before the database write occurs.

**How it works:**

1. Create `_pre_write_decision_check(workspace_id, item_type, item_data)` in
   `mcp_handlers.py`
2. It scans accepted decisions (from `.engrams/decisions/` and/or DB) for
   conflicts with the proposed write
3. If a `hard_block` conflict is found, it **raises an exception** that prevents
   the write and returns the conflict to the agent
4. If a `soft_warn` conflict is found, it proceeds but includes a warning in the
   response
5. Call this function at the **top** of `handle_log_decision`,
   `handle_log_system_pattern`, `handle_update_product_context`, etc. — before
   any DB write

**Scope of change:**
- `src/engrams/handlers/mcp_handlers.py` — add `_pre_write_decision_check()`,
  modify all write handlers to call it first
- `src/engrams/governance/conflict_detector.py` — add decision-scanning logic
- Possibly `src/engrams/core/exceptions.py` — new `GovernanceBlockError`
  exception class

**Tradeoffs:**
- ✅ **True enforcement** — cannot be bypassed by AI behavior
- ✅ Pre-write (nothing is persisted if blocked)
- ✅ Works without any governance setup (scopes/rules)
- ⚠️ More invasive change — touches every write handler
- ⚠️ Performance cost on every write (decision scanning)
- ⚠️ Tag/keyword matching may produce false positives that block legitimate
  writes

---

### Option D — Auto-Seed Governance Rules from Accepted Decisions

**What changes:** During `engrams init` (or on first connection), automatically
create a governance scope and generate `governance_rules` entries from accepted
decisions.

**How it works:**

1. During `create_database()` or `engrams init`, scan `.engrams/decisions/`
2. Auto-create a `team` governance scope if none exists
3. For each accepted decision, extract its tags and generate a `soft_warn` rule
   for that entity type with those tags as `required_tags` or `blocked_keywords`
4. The existing conflict detector now fires because scopes and rules exist

**Scope of change:**
- `src/engrams/db/database.py` — add auto-seeding logic to `create_database()`
- `src/engrams/governance/db_operations.py` — add `seed_rules_from_decisions()`
- `src/engrams/team_sync/indexer.py` — parse `.engrams/decisions/` files

**Tradeoffs:**
- ✅ Uses existing governance infrastructure as designed
- ✅ Makes the formal system work out of the box
- ⚠️ Rule generation from decision text is imprecise — what keywords/tags
  should be blocked vs. required?
- ⚠️ Generated rules may be too broad or too narrow
- ⚠️ Doesn't solve the fundamental issue that conflict detection is post-write
  and scope-gated

---

### Option E — Hybrid: Option A + Option B

**What changes:** Combine decision-aware conflict detection (Option A) with a
dedicated pre-check tool (Option B).

**How it works:**

1. **Option A piece:** Modify `_apply_governance_checks()` to always run
   decision-conflict checks, even without scopes. This is the safety net.
2. **Option B piece:** Add `check_planned_action` tool for agents to explicitly
   pre-check before large operations. This gives agents clear guidance.
3. If an agent skips the pre-check, the post-write safety net still catches
   conflicts and flags them in the response.

**Scope of change:** Combined scope of Options A and B.

**Tradeoffs:**
- ✅ Defense in depth — two layers
- ✅ Pre-check available for agents, post-write safety net for when they skip it
- ✅ No false blocking on the post-write path (warnings only)
- ⚠️ More code to maintain
- ⚠️ Post-write layer still means the write happened (just flagged)

---

## Recommendation

**Option E (Hybrid A + B)** provides the best balance:

- The pre-check tool (`check_planned_action`) catches major conflicts before
  any code changes begin — this would have stopped the PostgreSQL migration
  before any files were read
- The post-write safety net in `_apply_governance_checks()` catches anything
  that slips through when agents don't call the pre-check
- Neither layer requires formal governance setup (scopes/rules) to work

If a simpler first step is preferred, **Option A alone** is the minimum viable
fix — it ensures that the existing `_apply_governance_checks()` path always
checks accepted decisions, even without scopes.
