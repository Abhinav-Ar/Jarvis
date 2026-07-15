#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h}"
APP_DIR="$HOME/Library/Application Support/Jarvis"
MENU_APP="$HOME/Applications/Jarvis Menu.app"
LABEL="com.jarvis.voice"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
MENU_LABEL="com.jarvis.menu"
MENU_TARGET="$HOME/Library/LaunchAgents/$MENU_LABEL.plist"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Run ./setup.sh before installing the background service."
  exit 1
fi

mkdir -p "$APP_DIR/.runtime" "$HOME/Library/LaunchAgents" "$HOME/Applications"

# LaunchAgents cannot reliably read projects under macOS-protected Documents.
# Deploy a minimal private runtime under Application Support instead.
for file in orion.py orion_kernel.py orion_replay.py generation.py capability_families.py google_workspace.py app_installer.py project_workspace.py blender_worker.py blender_advanced_worker.py freecad_worker.py openscad_worker.py resolve_worker.py jarvis.py assist.py audio.py activity.py diagnostics.py fast_commands.py tools.py spot.py mac_tools.py integrations.py desktop.py git_tools.py task_engine.py agent_platform.py project_workflow.py execution_engine.py recovery.py requirements.txt start.sh; do
  /usr/bin/ditto "$PROJECT_DIR/$file" "$APP_DIR/$file"
done
/usr/bin/ditto "$PROJECT_DIR/.env" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
chmod +x "$APP_DIR/start.sh"

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  /opt/homebrew/bin/python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

# Build the native menu-bar controller as a local, ad-hoc-signed app bundle.
mkdir -p "$MENU_APP/Contents/MacOS" "$APP_DIR/.swift-cache"
/usr/bin/swiftc \
  -module-cache-path "$APP_DIR/.swift-cache" \
  -framework UserNotifications \
  -framework ScreenCaptureKit \
  -framework Vision \
  "$PROJECT_DIR/macos/JarvisHUDView.swift" \
  "$PROJECT_DIR/macos/JarvisMenu.swift" \
  -o "$MENU_APP/Contents/MacOS/JarvisMenu"
/usr/bin/swiftc \
  -module-cache-path "$APP_DIR/.swift-cache" \
  "$PROJECT_DIR/macos/JarvisDesktopHelper.swift" \
  -o "$MENU_APP/Contents/MacOS/JarvisDesktopHelper"
/usr/bin/ditto "$PROJECT_DIR/macos/JarvisMenu-Info.plist" "$MENU_APP/Contents/Info.plist"
/usr/bin/codesign --force --deep --sign - "$MENU_APP"

sed "s|__PROJECT_DIR__|$APP_DIR|g" "$PROJECT_DIR/macos/$LABEL.plist" > "$TARGET"
sed -e "s|__PROJECT_DIR__|$APP_DIR|g" -e "s|__MENU_APP__|$MENU_APP|g" \
  "$PROJECT_DIR/macos/$MENU_LABEL.plist" > "$MENU_TARGET"
plutil -lint "$TARGET"
plutil -lint "$MENU_TARGET"

launchctl bootout "gui/$UID/$MENU_LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true

load_agent() {
  local label="$1"
  local plist="$2"
  launchctl enable "gui/$UID/$label"
  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "gui/$UID" "$plist" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Could not load $label after five attempts. Check macOS launchd logs."
  return 1
}

load_agent "$LABEL" "$TARGET"
load_agent "$MENU_LABEL" "$MENU_TARGET"

echo "ORION is installed as a login background service."
echo "Runtime: $APP_DIR"
echo "Menu app: $MENU_APP"
echo "A colored '● ORION' controller is available in the macOS menu bar."
echo "Use ./orionctl status, ./orionctl logs, or ./orionctl stop."
