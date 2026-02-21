<div align="center">

<img src="./static/engram.sh.png" style="height:150px;" />

# Engrams

## Enhanced Memory & Knowledge Platform
</div>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A governance-aware, context-intelligent development platform built on the Model Context Protocol (MCP). Engrams transforms how AI agents understand and work with your projects by providing structured memory, intelligent context retrieval, and visual knowledge exploration.

**Forked from** [GreatScottyMac/context-portal](https://github.com/GreatScottyMac/context-portal) v0.3.13

[Features](#features) • [Installation](#installation) • [Quick Start](#quick-start) • [Documentation](#documentation)


---

## What is Engrams?

Engrams is an **intelligent project memory system** that helps AI assistants deeply understand your software projects. Instead of relying on simple text files or scattered documentation, Engrams provides a structured, queryable knowledge graph that captures:

- **Decisions**: Why you chose PostgreSQL over MongoDB, why you're using microservices
- **Progress**: Current tasks, blockers, what's in flight
- **Patterns**: Architectural patterns, coding conventions, system designs
- **Context**: Project goals, current focus, team agreements
- **Custom Data**: Glossaries, specifications, any structured project knowledge

**Key Benefits:**
- **Smarter AI Agents**: Give your AI assistant deep project understanding
- **Fast Retrieval**: Semantic search finds relevant context instantly
- **Knowledge Graph**: See how decisions, patterns, and code relate
- **Team Governance**: Enforce team standards while allowing individual flexibility
- **Token Efficient**: Smart budgeting returns only relevant context within token limits
- **Codebase-Aware**: Link decisions to actual code files for spatial context

---

## Features

### Structured Context Storage

Store your project knowledge in a structured SQLite database instead of scattered markdown files.

**Purpose**: Provide reliable, queryable storage for all project context with one database per workspace.

**Usage Example**:
```python
# Update product context (high-level project info)
update_product_context(
    workspace_id="/path/to/project",
    content={
        "name": "TaskMaster API",
        "purpose": "RESTful API for task management",
        "architecture": "Microservices with event sourcing",
        "tech_stack": ["Python", "FastAPI", "PostgreSQL", "Redis"]
    }
)

# Log a decision
log_decision(
    workspace_id="/path/to/project",
    summary="Use PostgreSQL for primary database",
    rationale="Need ACID guarantees, complex queries, and mature ecosystem",
    tags=["database", "architecture"]
)

# Track progress
log_progress(
    workspace_id="/path/to/project",
    description="Implement user authentication",
    status="IN_PROGRESS"
)
```

---

### Semantic Search & RAG

Vector embeddings enable semantic search - find relevant context by meaning, not just keywords.

**Purpose**: Enable Retrieval Augmented Generation (RAG) so AI agents can access precise, contextually relevant information.

**Usage Example**:
```python
# Semantic search across decisions
search_decisions_fts(
    workspace_id="/path/to/project",
    query_term="database performance optimization"
)
# Returns decisions about caching, indexing, query optimization

# Search custom data (specs, glossary, etc)
search_custom_data_value_fts(
    workspace_id="/path/to/project",
    query_term="authentication flow",
    category_filter="technical_specs"
)
```

**What you get**: ChromaDB-powered vector storage that understands semantic similarity, not just exact matches.

---

### Team Governance (Feature 1)

Two-layer hierarchy (team/individual) with conflict detection and amendment workflows.

**Purpose**: Enforce team standards while allowing individual developers flexibility. Prevent individual decisions from contradicting team-level architectural mandates.

**Usage Example**:
```python
# Create team and individual scopes
create_scope(
    workspace_id="/path/to/project",
    scope_type="team",
    scope_name="Core Architecture",
    created_by="tech_lead"
)

create_scope(
    workspace_id="/path/to/project",
    scope_type="individual",
    scope_name="alice_dev",
    parent_scope_id=1,
    created_by="alice"
)

# Set a team-level governance rule
log_governance_rule(
    workspace_id="/path/to/project",
    scope_id=1,
    rule_type="hard_block",
    entity_type="decision",
    rule_definition={"tags": ["database"], "keywords": ["MongoDB"]},
    description="Team has standardized on PostgreSQL - no MongoDB"
)

# When Alice tries to log a MongoDB decision, it gets blocked
log_decision(
    workspace_id="/path/to/project",
    scope_id=2,  # Alice's individual scope
    summary="Use MongoDB for analytics data",
    tags=["database"]
)
# Returns: ConflictError - "Conflicts with Team Decision #5"
```

**What you get**: Automatic conflict detection, amendment proposals, compliance tracking, and governance dashboards.

---

### Codebase Bindings (Feature 2)

Link Engrams entities to actual code files using glob patterns.

**Purpose**: Bridge the gap between "what we decided" and "where it lives in code". Give AI agents spatial awareness of the codebase.

**Usage Example**:
```python
# Bind a decision to the files it governs
bind_code_to_item(
    workspace_id="/path/to/project",
    item_type="decision",
    item_id=14,
    file_pattern="src/auth/**/*.py",
    binding_type="governed_by"
)

# Bind a pattern to its implementation
bind_code_to_item(
    workspace_id="/path/to/project",
    item_type="system_pattern",
    item_id=3,
    file_pattern="src/api/middleware/rate_limiter.py",
    symbol_pattern="RateLimiter",
    binding_type="implements"
)

# Get all relevant context for files you're editing
get_context_for_files(
    workspace_id="/path/to/project",
    file_paths=["src/auth/login.py", "src/auth/session.py"]
)
# Returns: All decisions, patterns, and governance rules bound to those files
```

**What you get**: Code-aware context retrieval, binding verification, automatic staleness detection.

---

### Context Budgeting (Feature 3)

Intelligent token-aware context selection with relevance scoring.

**Purpose**: Fit the most valuable context into your AI's token budget. No more dumping everything and hoping - get precisely ranked, budget-constrained results.

**Usage Example**:
```python
# Get the most relevant context for a task, within budget
get_relevant_context(
    workspace_id="/path/to/project",
    task_description="Implement rate limiting for the API",
    token_budget=4000,
    profile="task_focused",  # Prioritizes semantic similarity
    file_paths=["src/api/middleware/"]
)

# Returns:
# - Top-scored decisions about rate limiting, API design
# - Relevant system patterns
# - Code bindings for those files
# - All within 4000 tokens
# - Excluded items listed with scores (so you know what didn't fit)

# Preview context size before retrieval
estimate_context_size(
    workspace_id="/path/to/project",
    task_description="Add OAuth2 support"
)
# Returns: "147 relevant entities, ~12,500 tokens total"
# Recommends: "Use budget 3000 (minimal), 6000 (standard), or 12000 (comprehensive)"
```

**Scoring factors**:
- Semantic similarity to task
- Recency (newer items score higher)
- Reference frequency (graph centrality)
- Lifecycle status (active > superseded)
- Scope priority (team > individual)
- Code proximity (bound to files you're editing)

**What you get**: Configurable scoring profiles, transparent relevance scores, budget optimization, format selection (compact/standard/verbose).

---

### Project Onboarding (Feature 4)

Progressive briefing system for getting up to speed on any project.

**Purpose**: Generate structured, progressive briefings instead of raw data dumps. Perfect for new team members, returning to a project after time away, or starting a fresh AI session.

**Usage Example**:
```python
# Executive briefing (500 tokens) - for quick status check
get_project_briefing(
    workspace_id="/path/to/project",
    level="executive"
)
# Returns: Project purpose, current status, key risks

# Overview briefing (2000 tokens) - for developers day 1
get_project_briefing(
    workspace_id="/path/to/project",
    level="overview"
)
# Returns: Architecture, key decisions, active work, team conventions

# Detailed briefing (5000 tokens) - ready to contribute
get_project_briefing(
    workspace_id="/path/to/project",
    level="detailed"
)
# Returns: All active decisions with rationale, patterns with implementation,
#          task hierarchy, glossary, code bindings

# Comprehensive briefing - full knowledge export
get_project_briefing(
    workspace_id="/path/to/project",
    level="comprehensive",
    token_budget=20000
)
# Returns: Complete knowledge graph with all relationships

# Drill into a specific section
get_section_detail(
    workspace_id="/path/to/project",
    section_id="key_decisions",
    token_budget=3000
)
```

**What you get**: Structured briefings with staleness indicators, entity counts, data coverage reports, and drill-down capability.

---

### Knowledge Dashboard (Feature 5)

Browser-based visual explorer with optional local LLM chat.

**Purpose**: Explore your project knowledge visually without needing an AI agent or burning API tokens. Perfect for browsing decisions, visualizing the knowledge graph, and conversational exploration via local Ollama.

**Usage Example**:
```bash
# Start the dashboard (read-only, localhost only)
engrams-dashboard --workspace /path/to/project

# With Ollama chat enabled
engrams-dashboard --workspace /path/to/project \
                  --enable-chat \
                  --ollama-model llama3.2

# Custom port
engrams-dashboard --workspace /path/to/project --port 9000

# Auto-detect workspace
cd /path/to/project
engrams-dashboard
```

**What you see**:
- **Overview Dashboard**: Project stats, activity timeline, staleness indicators
- **Decision Explorer**: Filterable table with full-text search, tag navigation
- **Pattern Library**: System patterns with linked decisions and code bindings
- **Task Tracker**: Hierarchical progress view with status filtering
- **Knowledge Graph**: Interactive D3.js visualization showing all entity relationships
- **Custom Data Browser**: Category-based navigation with JSON pretty-printing
- **Governance Dashboard**: Scope hierarchy, active rules, compliance overview (if Feature 1 active)
- **Ollama Chat Panel**: Ask questions about your project using local LLM (optional)

**Security**: Binds to `127.0.0.1` (localhost only) by default. Read-only access - cannot modify data.

---

### Knowledge Graph & Relationships

Explicitly link entities to build a queryable relationship network.

**Purpose**: Capture how decisions relate to patterns, how tasks track decisions, how features depend on each other.

**Usage Example**:
```python
# Link a decision to the pattern that implements it
link_engrams_items(
    workspace_id="/path/to/project",
    source_item_type="decision",
    source_item_id=14,
    target_item_type="system_pattern",
    target_item_id=3,
    relationship_type="implements",
    description="Rate limiting pattern implements the API protection decision"
)

# Link a task to the decision it tracks
link_engrams_items(
    workspace_id="/path/to/project",
    source_item_type="progress_entry",
    source_item_id=42,
    target_item_type="decision",
    target_item_id=14,
    relationship_type="tracks"
)

# Get all items linked to a decision
get_linked_items(
    workspace_id="/path/to/project",
    item_type="decision",
    item_id=14
)
# Returns: Patterns that implement it, tasks tracking it, related decisions
```

**Common relationship types**: `implements`, `related_to`, `tracks`, `blocks`, `clarifies`, `depends_on`, `supersedes`, `resolves`

---

### Batch Operations & Export/Import

Efficient bulk operations and markdown export for version control.

**Purpose**: Log multiple items in one call, export for backup/sharing, import from version-controlled markdown.

**Usage Example**:
```python
# Log multiple decisions at once
batch_log_items(
    workspace_id="/path/to/project",
    item_type="decision",
    items=[
        {
            "summary": "Use FastAPI for REST API",
            "rationale": "Modern, fast, excellent typing support",
            "tags": ["framework", "api"]
        },
        {
            "summary": "Use Pydantic for validation",
            "rationale": "Built into FastAPI, strong type safety",
            "tags": ["validation", "types"]
        }
    ]
)

# Export everything to markdown
export_engrams_to_markdown(
    workspace_id="/path/to/project",
    output_path="./docs/engrams_export"
)

# Import from markdown (e.g., after cloning repo)
import_markdown_to_engrams(
    workspace_id="/path/to/project",
    input_path="./docs/engrams_export"
)
```

---

## Installation

### Prerequisites

- **Python 3.8+** ([Download](https://www.python.org/downloads/))
- **uv** (recommended) - Fast Python package manager ([Install](https://github.com/astral-sh/uv#installation))

### Recommended: Using `uvx`

The easiest way to use Engrams is via `uvx`, which handles environments automatically:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from", "engrams",
        "engrams",
        "--mode", "stdio",
        "--log-level", "INFO"
      ]
    }
  }
}
```

Add to your MCP client settings (e.g., Roo Code, Cline, Windsurf, Cursor).

**Note**: Most IDEs don't expand `${workspaceFolder}` for MCP servers. Engrams has automatic workspace detection, so you can omit `--workspace_id` at launch. The workspace is detected per-call using project indicators (.git, package.json, etc.).

### Developer Installation

For local development:

```bash
# Clone the repository
git clone https://github.com/yourusername/engrams.git
cd engrams

# Create virtual environment
uv venv

# Install dependencies
uv pip install -r requirements.txt

# Run in your IDE using local checkout
# See README "Installation for Developers" section for MCP config
```

---

## Quick Start

### 1. Configure Your MCP Client

Add Engrams to your MCP settings (see [Installation](#installation) section).

### 2. Add Custom Instructions

Copy the appropriate strategy file for your IDE:
- **Roo Code**: [`engrams-custom-instructions/roo_code_engrams_strategy`](engrams-custom-instructions/roo_code_engrams_strategy)
- **Cline**: [`engrams-custom-instructions/cline_engrams_strategy`](engrams-custom-instructions/cline_engrams_strategy)
- **Windsurf**: [`engrams-custom-instructions/cascade_engrams_strategy`](engrams-custom-instructions/cascade_engrams_strategy)
- **Generic**: [`engrams-custom-instructions/generic_engrams_strategy`](engrams-custom-instructions/generic_engrams_strategy)

Paste the entire content into your IDE's custom instructions field.

### 3. Bootstrap Your Project (Optional but Recommended)

Create [`projectBrief.md`](projectBrief.md) in your workspace root:

```markdown
# TaskMaster API

## Purpose
RESTful API for task management with team collaboration.

## Key Features
- User authentication (JWT)
- Task CRUD with assignments
- Real-time notifications
- Team workspaces

## Architecture
- Microservices pattern
- Event sourcing for task updates
- PostgreSQL for persistence
- Redis for caching

## Tech Stack
Python, FastAPI, PostgreSQL, Redis, Docker
```

On first initialization, your AI agent will offer to import this into Product Context.

### 4. Start Using Engrams

```
You: Initialize according to custom instructions

AI: [CONPORT_ACTIVE] Engrams initialized. Found projectBrief.md - imported to Product Context.
    What would you like to work on?

You: Add JWT authentication to the API

AI: I'll help with that. Let me retrieve relevant context...
    [Uses get_context_for_files for src/auth/**]
    [Finds Decision #7: "Use JWT tokens for stateless auth"]
    [Finds Pattern #3: "Token validation middleware"]

    Based on existing decisions and patterns, I'll implement JWT auth following
    the established middleware pattern...
```

---

## Automatic Workspace Detection

Engrams can automatically detect your project root - no hardcoded paths needed.

**Detection strategy** (priority order):
1. **Strong indicators**: `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`
2. **Multiple general indicators**: ≥2 of (README, license, build configs)
3. **Existing Engrams workspace**: `engrams/` directory present
4. **Environment variables**: `VSCODE_WORKSPACE_FOLDER`, `ENGRAMS_WORKSPACE`
5. **Fallback**: Current working directory (with warning)

**Diagnostic tool**:
```python
get_workspace_detection_info(workspace_id="unused")
# Returns: detected path, method used, indicators found
```

See [`UNIVERSAL_WORKSPACE_DETECTION.md`](UNIVERSAL_WORKSPACE_DETECTION.md) for full details.

---

## Available MCP Tools

All tools require `workspace_id` argument (string). Integer parameters accept numbers or digit strings.

### Core Context
- `get_product_context`, `update_product_context` - Project goals, features, architecture
- `get_active_context`, `update_active_context` - Current focus, recent changes

### Decisions
- `log_decision`, `get_decisions`, `search_decisions_fts`, `delete_decision_by_id`

### Progress
- `log_progress`, `get_progress`, `update_progress`, `delete_progress_by_id`

### Patterns
- `log_system_pattern`, `get_system_patterns`, `delete_system_pattern_by_id`

### Custom Data
- `log_custom_data`, `get_custom_data`, `delete_custom_data`
- `search_custom_data_value_fts`, `search_project_glossary_fts`

### Relationships
- `link_engrams_items`, `get_linked_items`

### Governance (Feature 1)
- `create_scope`, `get_scopes`
- `log_governance_rule`, `get_governance_rules`
- `check_compliance`, `get_scope_amendments`, `review_amendment`
- `get_effective_context`

### Codebase Bindings (Feature 2)
- `bind_code_to_item`, `get_bindings_for_item`, `get_context_for_files`
- `verify_bindings`, `get_stale_bindings`, `suggest_bindings`, `unbind_code_from_item`

### Context Budgeting (Feature 3)
- `get_relevant_context`, `estimate_context_size`
- `get_context_budget_config`, `update_context_budget_config`

### Onboarding (Feature 4)
- `get_project_briefing`, `get_briefing_staleness`, `get_section_detail`

### Utilities
- `get_item_history`, `get_recent_activity_summary`, `get_engrams_schema`
- `export_engrams_to_markdown`, `import_markdown_to_engrams`
- `batch_log_items`
- `get_workspace_detection_info`

See full parameter details in the original README or use `get_engrams_schema()`.

---

## Documentation

- **[Deep Dive](engrams_deep_dive.md)** - Architecture and design details
- **[Workspace Detection](UNIVERSAL_WORKSPACE_DETECTION.md)** - Auto-detection behavior
- **[Update Guide](v0.2.4_UPDATE_GUIDE.md)** - Database migration instructions
- **[Contributing](CONTRIBUTING.md)** - How to contribute
- **[AGENTS.md](AGENTS.md)** - Implementation strategy for Features 1-5
- **[Custom Instructions](engrams-custom-instructions/)** - IDE-specific strategies

---

## Architecture

- **Language**: Python 3.8+
- **Framework**: FastAPI (MCP server)
- **Database**: SQLite (one per workspace)
- **Vector Store**: ChromaDB (semantic search)
- **Migrations**: Alembic (schema evolution)
- **Protocol**: Model Context Protocol (STDIO or HTTP)

```
src/engrams/
├── main.py                 # Entry point, CLI args
├── server.py               # FastMCP server, tool registration
├── db/                     # Database layer
│   ├── database.py         # SQLite operations
│   ├── models.py           # Pydantic models
│   └── migrations/         # Alembic migrations
├── handlers/               # MCP tool handlers
├── governance/             # Feature 1: Team governance
├── bindings/               # Feature 2: Codebase bindings
├── budgeting/              # Feature 3: Context budgeting
├── onboarding/             # Feature 4: Project briefings
└── dashboard/              # Feature 5: Visual explorer
```

---

## Contributing

We welcome contributions! Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for:
- Code of conduct
- Development setup
- Pull request process
- Testing requirements

---

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

---

## Acknowledgments

- Forked from [GreatScottyMac/context-portal](https://github.com/GreatScottyMac/context-portal) v0.3.13
- Thanks to [@cipradu](https://github.com/cipradu) for integer-string coercion implementation
- Built on the [Model Context Protocol](https://modelcontextprotocol.io/)

---

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/engrams/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/engrams/discussions)

---

<div align="center">

**[⬆ Back to Top](#engrams)**

Built with care for better AI-assisted development

</div>
