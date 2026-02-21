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

---

## Setup

### MCP Server Configuration

Engrams runs as a Model Context Protocol (MCP) server. Configure it in your MCP client's settings file (typically `mcp.json` or in your IDE's MCP configuration). The easiest way to use Engrams is via `uvx`, which automatically manages the Python environment:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from",
        "engrams",
        "engrams",
        "--mode",
        "stdio",
        "--log-level",
        "INFO"
      ]
    }
  }
}
```

#### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--mode` | Communication mode: `stdio` or `http` | `stdio` |
| `--log-level` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `--workspace_id` | Explicit workspace path (optional - auto-detected if omitted) | Auto-detected |
| `--port` | Port for HTTP mode | `8000` |

**Note:** Engrams automatically detects your workspace using project indicators (`.git`, `package.json`, `pyproject.toml`, etc.), so you typically don't need to specify `--workspace_id`.

#### IDE-Specific Setup

Add the MCP configuration to your IDE's settings:

- **Roo Code**: Settings → MCP Servers
- **Cline**: `.cline/cline_mcp_config.json`
- **Windsurf**: Cascade settings
- **Cursor**: Settings → MCP Servers
- **Claude Desktop**: `~/.config/Claude/claude_desktop_config.json` (macOS/Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

---

## Features

### Structured Context Storage

Store your project knowledge in a structured SQLite database instead of scattered markdown files.

**Purpose**: Provide reliable, queryable storage for all project context with one database per workspace.

**How to use it:**

```
You: "Log this decision: We're using PostgreSQL for the primary database
     because we need ACID guarantees and complex query support"

AI: Decision logged to Engrams:
    Decision #23: Use PostgreSQL for primary database
    Rationale: ACID guarantees, complex queries, mature ecosystem
    Tags: database, architecture
```

**Later, when working on related features:**

```
You: "I'm implementing the user data persistence layer.
     What decisions should guide this?"

AI: Found relevant decision:
    Decision #23: PostgreSQL is our primary database

    I'll implement using SQLAlchemy with PostgreSQL...
```

---

### Semantic Search & RAG

Vector embeddings enable semantic search - find relevant context by meaning, not just keywords.

**Purpose**: Enable Retrieval Augmented Generation (RAG) so AI agents can access precise, contextually relevant information.

**How to use it:**

```
You: "How should I handle caching for better performance?"

AI: Searching for relevant decisions...

    Found:
    • Decision #8: Use Redis for session caching
    • Decision #15: Cache invalidation strategy (TTL-based)
    • Decision #22: Database query optimization with indexes

    Based on these decisions, I recommend implementing Redis
    for session caching with a 24-hour TTL...
```

**What you get**: Your AI finds relevant context by understanding meaning, not just exact keyword matches. Ask about "performance optimization" and it finds decisions about caching, indexing, and query optimization.

---

### Team Governance

Two-layer hierarchy (team/individual) with conflict detection and amendment workflows.

**Purpose**: Enforce team standards while allowing individual developers flexibility. Prevent individual decisions from contradicting team-level architectural mandates.

**How to use it:**

```
You: "I want to use MongoDB for the analytics module"

AI: ⚠️ Governance Conflict Detected

    Your proposal conflicts with Team Decision #5:
    "Standardize on PostgreSQL for all data storage"
    Scope: Core Architecture (Team-level)

    This is a hard block. Would you like to propose an amendment?
```

**When you need an exception:**

```
You: "Propose an amendment to allow InfluxDB for time-series metrics"

AI: Amendment proposal created:
    Amendment #2 to Decision #5
    Proposal: Allow InfluxDB for time-series metrics data
    Rationale: PostgreSQL isn't optimized for high-volume time-series
    Status: Pending team review

    Your tech lead will be notified.
```

---

### Codebase Bindings

Link Engrams entities to actual code files using glob patterns.

**Purpose**: Bridge the gap between "what we decided" and "where it lives in code". Give AI agents spatial awareness of the codebase.

**How to use it:**

```
You: "Bind the rate limiting decision to the middleware implementation
     in src/api/middleware/rate_limiter.py"

AI: Binding created:
    Decision #14 (Rate limiting) → src/api/middleware/rate_limiter.py
    Relationship: implements
```

**When working on related code:**

```
You: "I'm adding a new API endpoint. What patterns should I follow?"

AI: Checking code context for src/api/endpoints/...

    Found Decision #14: Rate limiting (1000 req/min)
    Implementation: src/api/middleware/rate_limiter.py

    I'll apply the rate limiting middleware to your new endpoint...
```

---

### Context Budgeting

Intelligent token-aware context selection with relevance scoring.

**Purpose**: Fit the most valuable context into your AI's token budget. No more dumping everything and hoping - get precisely ranked, budget-constrained results.

**How to use it:**

```
You: "I need to implement rate limiting for the API.
     Give me the most relevant context within 4000 tokens"

AI: Retrieving relevant context (4000 token budget)...

    Top-scored items:
    ✓ Decision #14: API rate limiting requirements (1000 req/min)
    ✓ Pattern #8: Redis-based token bucket implementation
    ✓ Code binding: src/api/middleware/rate_limiter.py
    ✓ Related decision: Caching strategy with Redis

    Not included (lower relevance):
    ✗ Decision #22: Database indexing
    ✗ Pattern #3: Authentication flow

    I'll implement rate limiting using the token bucket pattern...
```

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

AI: [ENGRAMS_ACTIVE] Engrams initialized. Found projectBrief.md - imported to Product Context.
    What would you like to work on?

You: Add JWT authentication to the API

AI: I'll help with that. Let me retrieve relevant context...

    Found Decision #7: "Use JWT tokens for stateless auth"
    Found Pattern #3: "Token validation middleware"

    Based on existing decisions and patterns, I'll implement JWT auth
    following the established middleware pattern...

    [Implementation follows]
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

See [`UNIVERSAL_WORKSPACE_DETECTION.md`](UNIVERSAL_WORKSPACE_DETECTION.md) for full details.

---

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
