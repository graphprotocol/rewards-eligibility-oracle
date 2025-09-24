#!/bin/bash
# Project-specific setup script for graph
set -euo pipefail

echo "Running project-specific setup for graph..."

# Get the script directory and repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Script directory: $SCRIPT_DIR"
echo "Repository root: $REPO_ROOT"

# Add CONTAINER_BIN_PATH to PATH if it's set
if [ -n "${CONTAINER_BIN_PATH:-}" ]; then
  echo "CONTAINER_BIN_PATH is set to: $CONTAINER_BIN_PATH"
  echo "Adding CONTAINER_BIN_PATH to PATH..."

  # Add to current PATH
  export PATH="$CONTAINER_BIN_PATH:$PATH"

  # Add to .bashrc if not already there
  if ! grep -q "export PATH=\"\$CONTAINER_BIN_PATH:\$PATH\"" "$HOME/.bashrc"; then
    echo "Adding CONTAINER_BIN_PATH to .bashrc..."
    echo '
# Add CONTAINER_BIN_PATH to PATH if set
if [ -n "${CONTAINER_BIN_PATH:-}" ]; then
  export PATH="$CONTAINER_BIN_PATH:$PATH"
fi' >> "$HOME/.bashrc"
  fi

  echo "CONTAINER_BIN_PATH added to PATH"
else
  echo "CONTAINER_BIN_PATH is not set, skipping PATH modification"
fi

# Source shell customizations if available in PATH
if command -v shell-customizations &> /dev/null; then
  SHELL_CUSTOMIZATIONS_PATH=$(command -v shell-customizations)
  echo "Found shell customizations in PATH at: ${SHELL_CUSTOMIZATIONS_PATH}"
  echo "Sourcing shell customizations..."
  source "${SHELL_CUSTOMIZATIONS_PATH}"

  # Add to .bashrc if not already there
  if ! grep -q "source.*shell-customizations" "$HOME/.bashrc"; then
    echo "Adding shell customizations to .bashrc..."
    echo "source ${SHELL_CUSTOMIZATIONS_PATH}" >> "$HOME/.bashrc"
  fi
else
  echo "Shell customizations not found in PATH, skipping..."
fi

# Set up basic Git configuration (user.name and user.email from environment)
echo "Setting up basic Git configuration..."
if [[ -n "${GIT_USER_NAME:-}" && -n "${GIT_USER_EMAIL:-}" ]]; then
  echo "Setting Git user.name: $GIT_USER_NAME"
  git config --global user.name "$GIT_USER_NAME"
  echo "Setting Git user.email: $GIT_USER_EMAIL"
  git config --global user.email "$GIT_USER_EMAIL"
  echo "Git user configuration complete"
else
  echo "GIT_USER_NAME and/or GIT_USER_EMAIL not set - skipping Git user configuration"
  echo "You can set these manually with: git config --global user.name 'Your Name'"
  echo "and: git config --global user.email 'your.email@example.com'"
fi

echo "Project-specific setup completed"
