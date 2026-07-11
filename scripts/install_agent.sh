#!/bin/bash
# Install (or reinstall) the Turo co-host daemon as a launchd agent.
# Account-agnostic: derives all paths from this script's location, so it works
# from any checkout directory under any macOS user.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.turo.cohost.plist"

if [ ! -f "$ROOT/config.json" ]; then
  echo "ERROR: $ROOT/config.json missing."
  echo "  cp config.example.json config.json   # then fill in your values"
  exit 1
fi

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "creating virtualenv..."
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" -q install pytest
fi

sed "s|@ROOT@|$ROOT|g" "$ROOT/com.turo.cohost.plist.template" > "$PLIST"
launchctl bootout "gui/$(id -u)/com.turo.cohost" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "loaded. status line (pid / exit / label):"
launchctl list | grep com.turo.cohost || echo "  NOT LISTED — check $ROOT/logs/agent.log"
