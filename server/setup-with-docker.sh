#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker가 필요합니다. Docker Engine과 Compose를 먼저 설치하세요."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose 플러그인이 필요합니다."
  exit 1
fi

mkdir -p seminar-data seminar-inbox teams-sync-state dist

docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$PROJECT_DIR:/project" \
  -w /project \
  python:3.11-slim \
  python server/setup.py
