#!/usr/bin/env bash
# install.sh — add scout to your PATH
# Run once from ~/tools/scout/

set -euo pipefail

BOLD=$'\033[1m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"

mkdir -p "$INSTALL_DIR"
chmod +x "$SCRIPT_DIR/bin/scout"

# Write a launcher that resolves the scout binary at install time
# (absolute path baked in — if tools/ moves, re-run install.sh)
cat > "$INSTALL_DIR/scout" << EOF
#!/usr/bin/env bash
exec "$SCRIPT_DIR/bin/scout" "\$@"
EOF
chmod +x "$INSTALL_DIR/scout"

echo "${GREEN}✓${RESET} Installed to $INSTALL_DIR/scout"

# Detect shell config file
if [[ "$SHELL" == *"/zsh" ]]; then
  SHELL_RC="$HOME/.zshrc"
else
  SHELL_RC="$HOME/.bashrc"
fi

# PATH check
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
  echo ""
  echo "${YELLOW}⚠ $INSTALL_DIR is not in your PATH.${RESET}"
  echo ""
  echo "  Add to ~/${SHELL_RC##*/}:"
  echo "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
  echo ""
  echo "  Then: source ~/${SHELL_RC##*/}"
else
  echo ""
  echo "  Run: ${BOLD}scout ~/myProjectFolder${RESET}"
fi
echo ""
