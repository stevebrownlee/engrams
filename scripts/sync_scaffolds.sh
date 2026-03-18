#!/usr/bin/env bash
# sync_scaffolds.sh — Copy working .roo/ files into src/engrams/scaffolds/roo/
# Run this after modifying any system-prompt-flow-* or .roomodes file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCAFFOLD_DIR="$REPO_ROOT/src/engrams/scaffolds/roo"

echo "Syncing scaffold files from .roo/ → $SCAFFOLD_DIR"

cp "$REPO_ROOT/.roomodes" "$SCAFFOLD_DIR/roomodes"
echo "  ✓ roomodes"

for mode in architect code ask debug orchestrator; do
    src="$REPO_ROOT/.roo/system-prompt-flow-$mode"
    if [ -f "$src" ]; then
        cp "$src" "$SCAFFOLD_DIR/system-prompt-flow-$mode"
        echo "  ✓ system-prompt-flow-$mode"
    else
        echo "  ⚠ MISSING: $src"
    fi
done

echo ""
echo "Done. Run 'git diff src/engrams/scaffolds/' to review changes."
