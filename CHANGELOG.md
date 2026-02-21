# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-02-20

### Major Release: Engrams → Engrams Rebranding

This is the first major release of Engrams, a comprehensive rebranding and enhancement of Engrams v0.3.13.

#### Changed

- **Package Name**: `context-portal-mcp` → `engrams`
- **Module Name**: `context_portal_mcp` → `engrams`
- **CLI Commands**:
  - `engrams-mcp` → `engrams`
  - `engrams-dashboard` → `engrams-dashboard`
- **Directory Structure**:
  - `context_portal/` → `engrams/`
  - `.engrams_vector_data/` → `.engrams_vector_data/`
  - `engrams-custom-instructions/` → `engrams-custom-instructions/`
- **Environment Variables**:
  - `ENGRAMS_WORKSPACE` → `ENGRAMS_WORKSPACE` (legacy variable still supported for backward compatibility)
- **Documentation**:
  - `engrams_mcp_deep_dive.md` → `engrams_deep_dive.md`
  - All references to Engrams updated to Engrams throughout documentation
- **Tool Names**:
  - `link_engrams_items` → `link_engrams_items`
  - `get_engrams_schema` → `get_engrams_schema`
  - `export_engrams_to_markdown` → `export_engrams_to_markdown`
  - `import_markdown_to_engrams` → `import_markdown_to_engrams`

#### Added

- **Backward Compatibility Module** (`src/engrams/core/backward_compat.py`):
  - Automatic migration from Engrams to Engrams directory structure
  - Fallback support for legacy `ENGRAMS_WORKSPACE` environment variable
  - Automatic vector store migration from `.engrams_vector_data/` to `.engrams_vector_data/`
  - Optional compatibility symlink creation for development environments

- **Five Major Features** (from AGENTS.md):
  1. **Team/Individual Context Governance**: Two-layer hierarchy with conflict detection and amendment workflows
  2. **Codebase-Context Bridging**: Link decisions and patterns to specific files using glob patterns
  3. **Context Budgeting**: Intelligent token-aware context selection with relevance scoring
  4. **Project Onboarding**: Progressive briefing system (executive → comprehensive)
  5. **Visual Dashboard**: Browser-based knowledge graph explorer with optional Ollama chat

#### Migration Guide

Users upgrading from Engrams to Engrams will experience:

1. **Automatic Directory Migration**: Old `context_portal/` directories are automatically migrated to `engrams/`
2. **Database Preservation**: Existing `context.db` files are preserved and migrated intact
3. **Vector Store Migration**: Old `.engrams_vector_data/` is automatically moved to `.engrams_vector_data/`
4. **Environment Variable Fallback**: Legacy `ENGRAMS_WORKSPACE` environment variable still works (with deprecation warning)

For detailed migration instructions, see [MIGRATION_TO_ENGRAMS.md](MIGRATION_TO_ENGRAMS.md).

#### Breaking Changes

- Package name changed on PyPI: install `engrams` instead of `context-portal-mcp`
- CLI command names changed: use `engrams` instead of `engrams-mcp`
- Tool names changed in MCP interface (see "Changed" section above)
- Module imports must be updated: `from engrams` instead of `from context_portal_mcp`

#### Deprecations

- `ENGRAMS_WORKSPACE` environment variable is deprecated in favor of `ENGRAMS_WORKSPACE`
  - Legacy variable still supported for backward compatibility
  - Deprecation warning logged when legacy variable is used

#### Fork Attribution

This project is forked from [GreatScottyMac/context-portal](https://github.com/GreatScottyMac/context-portal) v0.3.13 with significant enhancements including team governance, codebase bindings, context budgeting, onboarding system, and visual dashboard.

---

## Previous Versions

For historical information about Engrams versions, see the original [context-portal repository](https://github.com/GreatScottyMac/context-portal).

### Engrams v0.3.13 (Base Fork)

The Engrams v1.0.0 release is based on Engrams v0.3.13, which included:

- Core MCP server implementation with FastAPI/FastMCP
- SQLite-based context storage (one database per workspace)
- Vector embeddings for semantic search via ChromaDB
- Full-text search (FTS5) for decisions and custom data
- Knowledge graph with typed relationships
- Alembic-managed schema migrations
- Multi-workspace support with automatic detection
- Custom instructions for various LLM agents (Roo Code, Cline, Cascade, Generic)
- Dashboard foundation (Flask-based)
- Comprehensive documentation and examples

---

## Important Notes

### Installation

Install the new package from PyPI:

```bash
pip install engrams
```

Or use `uvx` for direct execution:

```bash
uvx --from engrams engrams --mode stdio
```

### Configuration Updates

If you have existing MCP client configurations pointing to `engrams-mcp`, update them to use `engrams`:

**Before:**
```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": ["--from", "context-portal-mcp", "engrams-mcp", "--mode", "stdio"]
    }
  }
}
```

**After:**
```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": ["--from", "engrams", "engrams", "--mode", "stdio"]
    }
  }
}
```

### Custom Instructions

Update your LLM custom instructions to use the new strategy files from `engrams-custom-instructions/`:

- `roo_code_engrams_strategy`
- `cline_engrams_strategy`
- `cascade_engrams_strategy`
- `cascade_engrams_strategy_compact`
- `generic_engrams_strategy`
- `mem4sprint.md`
- `mem4sprint.schema_and_templates.md`

---

**Last Updated**: 2026-02-20
