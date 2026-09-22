#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

docker compose --profile teams build teams-sync
docker compose --profile teams run --rm --entrypoint python teams-sync /app/teams_sync/device_login.py
