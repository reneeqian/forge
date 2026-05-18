#!/usr/bin/env bash
# Installs the forge-panel VS Code extension by symlinking it into ~/.vscode/extensions/.
# Run this once; edits to src/ take effect after reloading VS Code (Cmd+Shift+P → "Reload Window").

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(node -e "process.stdout.write(require('./package.json').version)")
DEST="$HOME/.vscode/extensions/forge-panel-$VERSION"

if [ -L "$DEST" ]; then
  echo "Updating symlink: $DEST -> $SCRIPT_DIR"
  ln -sfn "$SCRIPT_DIR" "$DEST"
elif [ -e "$DEST" ]; then
  echo "ERROR: $DEST exists and is not a symlink. Remove it manually first."
  exit 1
else
  echo "Installing: $DEST -> $SCRIPT_DIR"
  ln -s "$SCRIPT_DIR" "$DEST"
fi

echo ""
echo "Done. Reload VS Code to activate the extension:"
echo "  Cmd+Shift+P → Reload Window"
echo ""
echo "The 'Forge' beaker icon will appear in the Activity Bar."
echo ""
echo "Optional settings (Cmd+, → search 'forge'):"
echo "  forge.workspaceConfig  – path to workspace.toml (auto-detected if blank)"
echo "  forge.forgePath        – path to forge CLI (auto-detected if blank)"
