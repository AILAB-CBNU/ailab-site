#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker Engine과 Docker Compose를 먼저 설치하세요. Python은 따로 필요하지 않습니다."
  exit 1
fi

if [[ ! -f .env ]]; then
  ./server/setup-with-docker.sh
fi

required=(TEAMS_TENANT_ID TEAMS_CLIENT_ID TEAMS_CLIENT_SECRET TEAMS_TEAM_ID TEAMS_CHANNEL_ID)
missing=()
for name in "${required[@]}"; do
  if ! grep -Eq "^${name}=.+" .env; then
    missing+=("$name")
  fi
done
if (( ${#missing[@]} )); then
  echo "설정이 비어 있습니다: ${missing[*]}"
  echo "./server/setup-with-docker.sh를 다시 실행하세요."
  exit 1
fi

mkdir -p seminar-data seminar-inbox teams-sync-state

if [[ ! -s teams-sync-state/delegated-token.json ]]; then
  echo "Teams 파일 계정 최초 로그인을 시작합니다."
  ./server/login-teams-files.sh
fi

docker compose --profile teams up -d --build

port="$(awk -F= '$1=="AILAB_PORT" {print $2}' .env | tail -1)"
port="${port:-8765}"
url="http://127.0.0.1:${port}/seminars.html"
for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
    echo "AI Lab 세미나 서버가 실행 중입니다: $url"
    docker compose --profile teams ps
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$url" >/dev/null 2>&1 || true
    fi
    exit 0
  fi
  sleep 1
done

echo "서버 상태 확인에 실패했습니다."
docker compose --profile teams logs --tail=80 website teams-sync
exit 1
