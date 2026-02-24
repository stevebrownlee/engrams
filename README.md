<div align="center">

<img src="https://raw.githubusercontent.com/stevebrownlee/engrams/refs/heads/main/static/engram.sh.png" style="height:150px;" />

# Engrams

## Persistent Project Memory for AI Assistants
</div>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Engrams is an MCP server that gives AI assistants structured, queryable memory for your projects — decisions, patterns, progress, and team rules — so you stop re-explaining your stack in every prompt.

**[Documentation](https://engrams.sh)** · **[Issues](https://github.com/stevebrownlee/engrams/issues)**

---

## Installation

### Prerequisites

- **Python 3.8+**
- **uv** — [Install](https://github.com/astral-sh/uv#installation)

### Add to Your MCP Client

Add the following to your MCP settings file (`mcp.json` or your IDE's MCP configuration):

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

Works with Roo Code, Cline, Cursor, Windsurf, Claude Code, and any MCP-compatible client.

> Workspace detection is automatic — no `--workspace_id` flag required. Engrams locates your project root per-call using `.git`, `package.json`, and similar indicators.

### Add Custom Instructions to Your Project

After installing, run `engrams init` from your project root to scaffold the strategy file for your AI tool:

```bash
engrams init --tool roo          # → .roo/rules/engrams_strategy
engrams init --tool cline        # → .clinerules
engrams init --tool cursor       # → .cursorrules
engrams init --tool windsurf     # → .windsurfrules
engrams init --tool claude-code  # → CLAUDE.md
engrams init --tool generic      # → engrams_strategy.md

engrams init --list              # See all supported tools
```

---

## Reducing Token Costs

Every time you start a new AI session, you're re-paying to re-establish project context: your stack, your conventions, your current task. With a large project and frequent sessions, this adds up fast.

Engrams stores that context once in a local SQLite database. Your AI assistant retrieves only what's relevant to the current task — not everything, not nothing.

**Before Engrams** — you prompt with background context every session:
```
You: We use FastAPI with SQLAlchemy and PostgreSQL. JWT auth is required on all
     routes. Follow the existing error handling pattern. Now add a /medications
     endpoint that...
```

**After Engrams** — the context is already there:
```
You: Add a /medications endpoint that...

AI: Retrieving relevant context...
    Decision #23: PostgreSQL primary database
    Decision #24: SQLAlchemy for all DB operations
    Decision #7: JWT auth required on all routes
    Pattern #5: Structured error handling

    Implementing with SQLAlchemy, JWT middleware, and structured error responses...
```

The more you log, the less you repeat. Features like [codebase bindings](https://engrams.sh/docs/features/bindings) and [context budgeting](https://engrams.sh/docs/features/budgeting) ensure that only the relevant context for each task is loaded — keeping prompt sizes (and costs) low even as the knowledge base grows.

---

## Establishing Team Rules

Engrams has a two-layer governance system: **team-level** rules that apply to everyone, and **individual-level** rules for personal workflow preferences.

### Log a team decision

```
You: "The team has decided to use PostgreSQL for the primary database because
     we need ACID guarantees and complex query support. This is a team-level
     architectural decision."

AI: Decision #23 logged:
    Use PostgreSQL for primary database
    Rationale: ACID guarantees, complex query support, mature ecosystem
    Scope: Team Architecture
    Tags: database, architecture
```

### Block conflicting proposals automatically

Once a team rule is in place, Engrams enforces it:

```
You: "I want to use MongoDB for the analytics module"

AI: ⚠ Governance Conflict Detected

    Your proposal conflicts with Team Decision #23:
    "Standardize on PostgreSQL for all data storage"
    Scope: Core Architecture (Team-level, hard block)

    Would you like to propose an amendment instead?
```

### Allow individual overrides

Individual developers can still log personal workflow strategies without affecting team rules:

```
You: "When I'm ready to create a PR, compare my branch with main, generate
     a summary of my changes, run autoflake on the API, and fix any critical
     lint errors."

AI: Individual strategy #4 created and saved.
```

See the [Governance documentation](https://engrams.sh/docs/features/governance) for scopes, amendment workflows, and compliance checks.

---

## Learn More

The [Engrams documentation site](https://engrams.sh) covers all features in detail:

- [How It Works](https://engrams.sh/docs/concepts/how-it-works)
- [Semantic Search](https://engrams.sh/docs/features/semantic-search)
- [Codebase Bindings](https://engrams.sh/docs/features/bindings)
- [Context Budgeting](https://engrams.sh/docs/features/budgeting)
- [Knowledge Graph](https://engrams.sh/docs/features/knowledge-graph)
- [Project Onboarding](https://engrams.sh/docs/features/onboarding)
- [Knowledge Dashboard](https://engrams.sh/docs/features/dashboard)
- [MCP Tool Reference](https://engrams.sh/docs/reference/mcp-tools)
- [Contributing](https://engrams.sh/docs/contributing)

---

## License

[Apache 2.0](LICENSE) · Forked from [GreatScottyMac/context-portal](https://github.com/GreatScottyMac/context-portal) v0.3.13
