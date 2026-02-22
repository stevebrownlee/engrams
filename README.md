<div align="center">

<img src="https://raw.githubusercontent.com/stevebrownlee/engrams/refs/heads/main/static/engram.sh.png" style="height:150px;" />

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

Engrams is an **intelligent project memory system** that helps AI assistants deeply understand your software projects. Instead of relying on simple text files or scattered documentation, Engrams provides a structured, queryable knowledge graph.

### Stored Knowledge

| Type | Description |
|------|-------------|
| **Decisions** | Why you chose PostgreSQL over MongoDB, why you're using microservices |
| **Progress** | Current tasks, blockers, what's in flight |
| **Patterns** | Architectural patterns, coding conventions, system designs |
| **Context** | Project goals, current focus, team agreements |
| **Custom Data** | Glossaries, specifications, any structured project knowledge |

## MCP Server Setup

Engrams runs as a Model Context Protocol (MCP) server. Configure it in your MCP client's settings file (typically `mcp.json` or in your IDE's MCP configuration). The easiest way to use Engrams is via `uvx`, which automatically manages the Python environment:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from",
        "engrams-mcp",
        "engrams-mcp",
        "--mode",
        "stdio",
        "--log-level",
        "INFO"
      ]
    }
  }
}
```

## Quick Start

### 1. Add Custom Instructions

The `engrams init` command scaffolds the correct strategy file into your project for your AI tool:

```bash
# See all supported tools
engrams init --list

# Initialize for your tool (run from your project root)
engrams init --tool roo          # → .roo/rules/engrams_strategy
engrams init --tool cline        # → .clinerules
engrams init --tool cursor       # → .cursorrules
engrams init --tool windsurf     # → .windsurfrules
engrams init --tool claude-code  # → CLAUDE.md
engrams init --tool claude-desktop  # prints instructions for manual paste
engrams init --tool generic      # → engrams_strategy.md
```

### 2. Bootstrap Engrams

If you have existing documents in your project, like a `README.md`, or `PROJECT_BRIEF.md` then have a quick conversation with your least expensive model and ask it to import that context into the Engrams database.

For example:

```
You: Initialize Engrams database by reading the contents of `README.md` file,
 `docs/ARCHITECTURE.md`, and `docs/GUIDELINES.md`

LLM: [ENGRAMS_ACTIVE] Engrams initialized. architectural patterns stored
and coding standard guideline decisions recorded.

What would you like to work on?
```

If you don't have any documents that currently store that information, you can start a conversation with your LLM of choice and start recording decisions _(see Team Governance section below)_.

For example:

```
You: "The team has decided to use PostgreSQL for the primary database
     because we need ACID guarantees and complex query support"

LLM: Decision logged to Engrams:
    Decision #23: Use PostgreSQL for primary database
    Rationale: ACID guarantees, complex queries, mature ecosystem
    Tags: database, architecture

You: "We also will be using SQLAlchemy as our ORM. Use it as the default
      strategy for all database operations"

LLM: Decision logged to Engrams:
    Decision #24: Use SQLAlchemy for all database operations and data validations
    Rationale: Greater security, data validation, declarative code
    Tags: database, orm
```

### 3. Start Using Engrams

```
You: Add JWT authentication to the API


LLM: I'll help with that. Let me retrieve relevant context...

    Found Decision #7: "Use JWT tokens for stateless auth"
    Found Pattern #3: "Token validation middleware"

    Based on existing decisions and patterns, I'll implement JWT auth
    following the established middleware pattern...

    [Implementation follows]
```

## Features

### Structured Context Storage

Store your project knowledge in a structured SQLite database that is organically used during your conversatsion with an LLM as you are planning, or building, features in your project. As you store more knowledge in Engrams, the less context you need to provide in your initial prompt.

```
You: "Implement a new `/medications` endpoint in the API that looks in the
      request JSON body for a `patient_id` property and returns any meds
      assigned to that patient. Let's start with authorized GET and POST
      operations only."

LLM: Found relevant decision:
    Decision #23: PostgreSQL is our primary database
    Decision #24: All operations will be written with SQLAlchemy
    Decision #7: JWT token authentication

    I'll extract the authenticated user from the request body for POST
    operations so that it can be recorded who is creating the record. The
    INSERT and SELECT operations will be written with SQLAlchemy
```

---

### Semantic Search

Your LLM finds relevant context by understanding meaning, not just exact keyword matches. Ask about "performance optimization" and it finds decisions about caching, indexing, and query optimization.


```
You: "How should I handle caching for better performance?"

LLM: Searching for relevant decisions...

    Found:
    • Decision #8: Use Redis for session caching
    • Decision #15: Cache invalidation strategy (TTL-based)
    • Decision #22: Database query optimization with indexes

    Based on these decisions, I recommend implementing Redis
    for session caching with a 24-hour TTL...
```

### Team Governance

Two-layer hierarchy (team/individual) with conflict detection and amendment workflows. Enforce team standards while allowing individual developers flexibility. Prevent individual decisions from contradicting team-level architectural mandates.

```
You: "I want to use MongoDB for the analytics module"

LLM: ⚠️ Governance Conflict Detected

    Your proposal conflicts with Team Decision #23:
    "Standardize on PostgreSQL for all data storage"
    Scope: Core Architecture (Team-level)

    This is a hard block. Would you like to propose an amendment?
```

**When you need an exception:**

```
You: "Propose an amendment to allow InfluxDB for time-series metrics"

LLM: Amendment proposal created:
    Amendment #2 to Decision #5
    Proposal: Allow InfluxDB for time-series metrics data
    Rationale: PostgreSQL isn't optimized for high-volume time-series
    Status: Pending team review
```

**When you want to store a personal decision:**

```
You: "When I tell you then I'm ready to create a PR, compare my branch
      with main and generate a succinct summary of my changes for me to use
      in the description. Then run `autoflake` in the API to ensure my imports
      are cleaned, and run `npm run lint -- --fix` and resolve any critical
      issues that it finds."

LLM: Individual strategy #4 created:
     Code summarization description generated when you are ready to create
     your PR. I'll fix any linting errors in the JavaScript code and any
     obsolete imports in the Python code.
```


---

### Codebase Bindings

Link decisions and patterns to code paths using glob patterns. When AI agents edit files, bound context surfaces automatically — no manual prompting and no loading the entire knowledge base.

**Bind decisions to code areas once:**

```
You: "Bind the SQLAlchemy decision to the data layer, the JWT auth
      decision to the auth module, and the error handling pattern to
      all route files"

AI: Bindings created:
    Decision #24 (SQLAlchemy ORM) → src/db/**/*.py
    Decision #7 (JWT auth)        → src/auth/**/*.py
    Pattern #5 (Error handling)   → src/api/routes/**/*.py
```

**Then the context follows the code — automatically:**

```
You: "Add a new route in src/api/routes/medications.py that queries
      src/db/repositories/medications.py"

AI: Checking context for files being edited...

    src/api/routes/medications.py is bound to:
    ✓ Pattern #5: Structured error handling (try/except with AppError)
    ✓ Decision #7: JWT auth required on all routes
    ✓ Decision #14: Rate limiting at 1000 req/min

    src/db/repositories/medications.py is bound to:
    ✓ Decision #24: Use SQLAlchemy for all DB operations
    ✓ Decision #23: PostgreSQL is the primary database

    Implementing with SQLAlchemy queries, JWT middleware,
    rate limiting, and structured error responses...
```

Without bindings, you'd need to remind the AI about each of those five decisions in your prompt — or hope it retrieves them all via search. With bindings, touching the file is enough.

---

### Context Budgeting

Intelligent token-aware context selection that works behind the scenes. Instead of loading every decision, pattern, and glossary term into the prompt, Engrams scores each item by relevance and fits only the highest-value context into the AI's token window.

**Purpose**: Your Engrams database grows over time — 50 decisions, 20 patterns, dozens of glossary terms. Context budgeting ensures the AI loads only what matters for the current task, keeping prompts fast and costs low.

**What it looks like in practice:**

```
You: "Add WebSocket support for real-time notifications"

AI: Retrieving project context...

    Loaded 6 of 43 Engrams items (budget: 4000 tokens):
    ✓ Decision #31: Use WebSockets for real-time features
    ✓ Pattern #8: Event-driven pub/sub architecture
    ✓ Decision #7: JWT auth (tokens must validate on WS connect)
    ✓ Decision #19: Redis for pub/sub message brokering
    ✓ Pattern #12: Connection lifecycle management
    ✓ Glossary: "notification_channel" schema definition

    Skipped 37 lower-relevance items (database indexing,
    REST endpoint conventions, deployment configs, etc.)

    I'll implement a WebSocket endpoint using the pub/sub
    pattern with Redis, authenticating via JWT on connect...
```

The developer never asked for "relevant context" — the AI requested it transparently. Without budgeting, all 43 items would be loaded into the prompt, burning tokens on database indexing decisions and deployment patterns that have nothing to do with WebSockets.

---

### Project Onboarding

Progressive briefing system for getting up to speed on any project.

**Purpose**: Generate structured, progressive briefings instead of raw data dumps. Perfect for new team members, returning to a project after time away, or starting a fresh AI session.

**How to use it:**

```
You: "Give me a project briefing"

AI: PROJECT BRIEFING: TaskMaster API

    Purpose: RESTful API for task management with team collaboration

    Key Decisions:
    • PostgreSQL for primary database (ACID guarantees)
    • JWT tokens for stateless authentication
    • Redis for session caching
    • Microservices architecture with event sourcing

    Current Status:
    • User authentication: Complete
    • Task CRUD: In progress
    • Real-time notifications: Planned

    Tech Stack: Python, FastAPI, PostgreSQL, Redis, Docker
```

**For deeper context:**

```
You: "Tell me more about the authentication system"

AI: AUTHENTICATION SYSTEM DETAILS

    Decision #7: Use JWT tokens for stateless auth
    Rationale: Scales better than sessions, works with microservices

    Pattern #3: Token validation middleware
    Implementation: src/auth/middleware.py

    Related decisions:
    • Decision #12: Token refresh strategy (7-day expiry)
    • Decision #18: CORS policy for token endpoints

    Code locations:
    • src/auth/login.py - Token generation
    • src/auth/middleware.py - Token validation
    • src/auth/session.py - Session management
```

---

### Knowledge Dashboard

Browser-based visual explorer with optional local LLM chat.

**Purpose**: Explore your project knowledge visually without needing an AI agent or burning API tokens. Perfect for browsing decisions, visualizing the knowledge graph, and conversational exploration via local Ollama.

**How to use it:**

```bash
# Start the dashboard (auto-detects workspace from current directory)
cd /path/to/project
engrams dashboard

# Explicit workspace path
engrams dashboard --workspace /path/to/project

# With Ollama chat enabled
engrams dashboard --enable-chat --ollama-model llama3.2

# Custom port
engrams dashboard --port 9000

# Combine flags
engrams dashboard --workspace /path/to/project --enable-chat --port 9000
```

> **Note**: `--workspace` is optional. When omitted, Engrams uses the current working directory automatically. The legacy `engrams-dashboard` command remains available for backward compatibility.

**What you see**:
- **Overview Dashboard**: Project stats, activity timeline, staleness indicators
- **Decision Explorer**: Filterable table with full-text search, tag navigation
- **Pattern Library**: System patterns with linked decisions and code bindings
- **Task Tracker**: Hierarchical progress view with status filtering
- **Knowledge Graph**: Interactive D3.js visualization showing all entity relationships
- **Custom Data Browser**: Category-based navigation with JSON pretty-printing
- **Governance Dashboard**: Scope hierarchy, active rules, compliance overview
- **Ollama Chat Panel**: Ask questions about your project using local LLM (optional)

**Security**: Binds to `127.0.0.1` (localhost only) by default. Read-only access - cannot modify data.

---

### Knowledge Graph & Relationships

Explicitly link entities to build a queryable relationship network.

**Purpose**: Capture how decisions relate to patterns, how tasks track decisions, how features depend on each other.

**How to use it:**

```
You: "Link the rate limiting pattern to Decision #14.
     The pattern implements the decision"

AI: Relationship created:
    Pattern #8 (Rate limiting) implements Decision #14 (API protection)

    Now when you review Decision #14, you'll see which patterns
    implement it. When you work on the rate limiting pattern,
    you'll see the decision it addresses.
```

**Exploring relationships:**

```
You: "Show me everything related to the authentication decision"

AI: Linked items for Decision #7 (JWT authentication):

    Implements:
    • Pattern #3: Token validation middleware
    • Pattern #5: Token refresh strategy

    Tracks:
    • Progress #12: Implement JWT endpoints
    • Progress #18: Add token refresh logic

    Related Decisions:
    • Decision #12: Token expiry (7 days)
    • Decision #18: CORS policy

    Code Bindings:
    • src/auth/login.py
    • src/auth/middleware.py
```

**Common relationship types**: `implements`, `related_to`, `tracks`, `blocks`, `clarifies`, `depends_on`, `supersedes`, `resolves`

---

### Batch Operations & Export/Import

Efficient bulk operations and markdown export for version control.

**Purpose**: Log multiple items in one call, export for backup/sharing, import from version-controlled markdown.

**How to use it:**

```
You: "Log these tech stack decisions all at once:
     - FastAPI for REST API
     - Pydantic for validation
     - SQLAlchemy for ORM
     - Alembic for migrations
     - pytest for testing"

AI: Logged 5 decisions:
    ✓ Decision #24: Use FastAPI for REST API
    ✓ Decision #25: Use Pydantic for validation
    ✓ Decision #26: Use SQLAlchemy for ORM
    ✓ Decision #27: Use Alembic for migrations
    ✓ Decision #28: Use pytest for testing

    All tagged with "tech_stack" for easy retrieval.
```

**Export for version control:**

```
You: "Export all project knowledge to markdown"

AI: Exporting Engrams database to markdown...

    Created ./docs/engrams_export/ with:
    • decisions.md (28 decisions)
    • patterns.md (8 patterns)
    • progress.md (15 tasks)
    • glossary.md (12 terms)
    • relationships.md (all links)

    You can commit this to version control.
```

**Import after cloning:**

```
You: "Import the project knowledge from markdown"

AI: Importing from ./docs/engrams_export/...

    Imported:
    ✓ 28 decisions
    ✓ 8 patterns
    ✓ 15 progress items
    ✓ 12 glossary terms
    ✓ All relationships

    Your project memory is fully restored.
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
        "--from", "engrams-mcp",
        "engrams-mcp",
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

## Available MCP Tools

Your AI assistant uses these tools automatically. You don't need to call them directly.

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

### Governance
- `create_scope`, `get_scopes`
- `log_governance_rule`, `get_governance_rules`
- `check_compliance`, `get_scope_amendments`, `review_amendment`
- `get_effective_context`

### Codebase Bindings
- `bind_code_to_item`, `get_bindings_for_item`, `get_context_for_files`
- `verify_bindings`, `get_stale_bindings`, `suggest_bindings`, `unbind_code_from_item`

### Context Budgeting
- `get_relevant_context`, `estimate_context_size`
- `get_context_budget_config`, `update_context_budget_config`

### Onboarding
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

## Contributing

We welcome contributions! Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for:
- Code of conduct
- Development setup
- Pull request process
- Testing requirements

---

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

## Acknowledgments

- Forked from [GreatScottyMac/context-portal](https://github.com/GreatScottyMac/context-portal) v0.3.13

## Support

- **Issues**: [GitHub Issues](https://github.com/stevebrownlee/engrams/issues)
