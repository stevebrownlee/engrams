# Universal Workspace Detection (Engrams MCP)

This document describes the universal workspace auto-detection system integrated in version 0.3.0 (`WorkspaceDetector` and `resolve_workspace_id`). It removes the need to hardcode `--workspace_id` for most MCP client launches, especially when IDE variables like `${workspaceFolder}` fail to expand.

---

## Goals

- Reduce configuration friction.
- Support heterogeneous project types (Python, Node.js, Rust, Go, Java, PHP, Ruby, generic build systems).
- Honor existing Engrams workspaces seamlessly.
- Fail safe: never block startup due to an unexpanded placeholder path.
- Provide diagnostics via an MCP tool (`get_workspace_detection_info`).

---

## Core Components

1. `WorkspaceDetector` (multi-strategy upward search).
2. `auto_detect_workspace(start_path)`.
3. `resolve_workspace_id(provided_workspace_id, auto_detect, start_path)`.
4. CLI flags:
   - `--auto-detect-workspace` (default: enabled)
   - `--no-auto-detect`
   - `--workspace-search-start <path>`
5. MCP tool: `get_workspace_detection_info`.

---

## Detection Strategies (Priority Order)

1. **Strong Indicators**
   Presence (in current or ancestor directory, up to max depth) of any high-confidence files:
   - `package.json`
   - `.git`
   - `pyproject.toml`
   - `Cargo.toml`
   - `go.mod`
   - `pom.xml`
   If found, the directory is validated (light structural/content checks).

2. **Multiple General Indicators**
   If two or more of a broader set exist (e.g., `README.md`, `LICENSE`, `requirements.txt`, `CMakeLists.txt`, `Makefile`, `setup.py`, `.gitignore`) the directory is treated as a workspace.

3. **Existing Engrams Workspace**
   A `engrams/` directory (database or prior usage) signals a valid root.

4. **MCP / Environment Context**
   Environment variables (if directories):
   - `VSCODE_WORKSPACE_FOLDER`
   - `ENGRAMS_WORKSPACE`

5. **Fallback**
   Start directory (with a warning) if nothing else matches.

---

## CLI Usage Examples

### Minimal (auto-detect only)
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

### Disable Auto-Detection Explicitly
```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from", "engrams-mcp",
        "engrams-mcp",
        "--mode", "stdio",
        "--no-auto-detect",
        "--workspace_id", "/absolute/path/to/project"
      ]
    }
  }
}
```

### Custom Start Path (deep launch scenario)
```bash
engrams-mcp --mode stdio --workspace-search-start ../../
```

---

## MCP Tool: `get_workspace_detection_info`

Returns a diagnostic payload:
- `start_path`
- `detected_workspace`
- `engrams_path`
- `detection_method`
  (`strong_indicators` | `multiple_indicators` | `existing_engrams` | `fallback`)
- `indicators_found`
- `environment_variables` subset

Use this when:
- Investigating unexpected root selection.
- Debugging multi-repo monorepos.
- Verifying environment-based overrides.

---

## Special Case Handling

- Literal `${workspaceFolder}` (unexpanded): Logged at WARNING then ignored; auto-detection proceeds.
- Non-existent provided path: If passed explicitly and does not exist, detection still runs (future enhancement may validate early).
- Nested repos (e.g., Git submodules): First qualifying ancestor wins; use `--workspace-search-start` to narrow if needed.

---

## Edge Cases

| Scenario | Result | Mitigation |
|----------|--------|------------|
| Empty directory (no indicators) | Fallback to start path | Provide explicit `--workspace_id` or add project files |
| Multi-language polyrepo (e.g., `backend/`, `frontend/`) | Strong indicator may pick nested path depending on start | Launch from desired subtree or override start path |
| IDE launches from temporary wrapper dir | Upward search climbs to actual repo root | None needed |
| User wants per-tool isolation | Disable auto-detect and provide explicit `workspace_id` each call | Use `--no-auto-detect` |

---

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|--------------|-------|
| Wrong directory selected | Multiple candidate ancestors | Pin with `--workspace-search-start` or explicit `--workspace_id` |
| Detection always falls back | No indicators present | Add a sentinel file (`README.md`, `pyproject.toml`, etc.) |
| Literal `${workspaceFolder}` logged | IDE did not expand variable | Remove flag or rely on auto-detect |
| Tool reports `fallback` unexpectedly | Indicators below start path only | Adjust `--workspace-search-start` to deeper path |

---

## Migration Guidance (Pre-0.3.0 → 0.3.0+)

| Previous Configuration | Recommended Now |
|------------------------|-----------------|
| Hardcoded absolute `--workspace_id` | Remove if single-root and rely on auto-detect |
| Multiple client configs per project | Consolidate to one config (unless isolation needed) |
| Scripts wrapping launch with path injection | Simplify to `uvx --from engrams-mcp engrams-mcp --mode stdio` |

No database changes required; behavior is runtime-only.

---

## Implementation Notes

- Search depth default: 10 ancestor levels.
- Validation heuristics are intentionally lightweight (avoid heavy parsing).
- Strategy order biases correctness over pure speed; early return on first success.
- Logging levels:
  - `DEBUG`: Iteration details
  - `INFO`: Successful detection outcome
  - `WARNING`: Fallback, unexpanded placeholders

---

## Future Enhancements (Planned / Considerations)

- Configurable max depth via CLI.
- Ignore-list / anchor-file override (e.g., `.engrams-root`).
- Multi-root resolution returning a set for advanced clients.
- Persistent cache of last good detection (optional).

---

## Attribution

This feature supersedes an earlier external contribution proposal (original PR #60, stalled). Core ideas, detection layering, and environment fallbacks were refined and integrated in 0.3.0. Prior contributor intent is acknowledged in project history.

---

## Best Practices Summary

- Let auto-detect run unless you have a clear reason to disable it.
- Use the diagnostic tool before filing issues.
- Keep at least one strong or multiple general indicators in the true root.
- In monorepos requiring multiple logical knowledge graphs, disable auto-detect and supply distinct `workspace_id` values.

---

For questions or improvements, open an issue referencing “Universal Workspace Detection”.