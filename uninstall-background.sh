#!/bin/zsh
set -e

LABEL="com.jarvis.voice"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
MENU_LABEL="com.jarvis.menu"
MENU_TARGET="$HOME/Library/LaunchAgents/$MENU_LABEL.plist"

launchctl bootout "gui/$UID/$MENU_LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
if [[ -f "$TARGET" ]]; then
  rm "$TARGET"
fi
if [[ -f "$MENU_TARGET" ]]; then
  rm "$MENU_TARGET"
fi

echo "ORION background service was removed. Project files and logs were preserved."
