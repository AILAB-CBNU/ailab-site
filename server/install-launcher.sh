#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DESKTOP_DIR" "$HOME/.local/share/icons"

ICON_PATH="$HOME/.local/share/icons/cbnu-ailab-seminar.png"
cp "$PROJECT_DIR/teams-app/color.png" "$ICON_PATH"
LAUNCHER="$DESKTOP_DIR/AI Lab 세미나 서버.desktop"

cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=AI Lab 세미나 서버
Comment=웹사이트와 Teams 세미나 자동 수집기를 시작합니다
Exec="$PROJECT_DIR/server/start-server.sh"
Icon=$ICON_PATH
Terminal=true
Categories=Development;Network;
EOF

chmod +x "$LAUNCHER" "$PROJECT_DIR/server/start-server.sh" "$PROJECT_DIR/server/setup-with-docker.sh" "$PROJECT_DIR/server/login-teams-files.sh" "$PROJECT_DIR/server/setup.py"
gio set "$LAUNCHER" metadata::trusted true >/dev/null 2>&1 || true
echo "바탕화면 실행 아이콘을 만들었습니다: $LAUNCHER"
