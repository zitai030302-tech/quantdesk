#!/bin/zsh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$REPO_DIR/artifacts/desktop_launcher"
APP_PATH="$BUILD_DIR/Quant 启动器.app"
CONTENTS_DIR="$APP_PATH/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
TEMPLATE_FILE="$REPO_DIR/scripts/quant_app_launcher.template.sh"
LAUNCHER_FILE="$MACOS_DIR/quant-launcher"
PLIST_FILE="$CONTENTS_DIR/Info.plist"
ICON_SRC="/System/Applications/Utilities/Terminal.app/Contents/Resources/Terminal.icns"
ICON_NAME="QuantLauncher.icns"

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
rm -rf "$APP_PATH"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

sed "s|__REPO_DIR__|$REPO_DIR|g" "$TEMPLATE_FILE" >"$LAUNCHER_FILE"
chmod +x "$LAUNCHER_FILE"

cat >"$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleExecutable</key>
  <string>quant-launcher</string>
  <key>CFBundleIconFile</key>
  <string>$ICON_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>local.quant.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Quant 启动器</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

if [[ -f "$ICON_SRC" ]]; then
  cp "$ICON_SRC" "$RESOURCES_DIR/$ICON_NAME"
fi

if command -v codesign >/dev/null 2>&1; then
  if ! codesign --force --deep --sign - "$APP_PATH"; then
    echo "warning: codesign failed, app bundle remains unsigned" >&2
  fi
fi

echo "$APP_PATH"
