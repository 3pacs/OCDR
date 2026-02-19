#!/bin/bash
set -euo pipefail

# Only run in remote Claude Code on the web sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo "Session start hook: no dependencies to install yet."

# When the project adds a package manager, install dependencies here.
# Examples:
#   npm install
#   pip install -r requirements.txt
#   poetry install
#   cargo fetch
#   bundle install
