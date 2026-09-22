#!/usr/bin/env python3
"""One-time interactive setup for the lab server PC."""

from __future__ import annotations

import getpass
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
MAP_PATH = ROOT / "seminar_service" / "config" / "presenter-map.json"
DEFAULT_TENANT_ID = ""
DEFAULT_APP_ID = ""


def load_env() -> dict[str, str]:
    result: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
    return result


def ask(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else ""
    while True:
        value = (getpass.getpass(label + suffix + ": ") if secret else input(label + suffix + ": ")).strip()
        if value:
            return value
        if default:
            return default
        print("필수 값입니다.")


def main() -> None:
    existing = load_env()
    print("\nCBNU AI Lab 서버 최초 설정\n")
    tenant_id = ask("Microsoft tenant ID", existing.get("TEAMS_TENANT_ID", DEFAULT_TENANT_ID))
    client_id = ask("Entra application (client) ID", existing.get("TEAMS_CLIENT_ID", DEFAULT_APP_ID))
    client_secret = ask("Entra client secret value", existing.get("TEAMS_CLIENT_SECRET", ""), secret=True)
    team_id = ask("Teams team ID", existing.get("TEAMS_TEAM_ID", ""))
    channel_id = ask("Teams seminar channel ID", existing.get("TEAMS_CHANNEL_ID", ""))
    public_url = ask("Public HTTPS website origin", existing.get("TEAMS_PUBLIC_URL", ""))

    values = {
        "SEMINAR_UPLOAD_TOKEN": existing.get("SEMINAR_UPLOAD_TOKEN") or secrets.token_hex(32),
        "AILAB_UID": str(getattr(os, "getuid", lambda: 1000)()),
        "AILAB_GID": str(getattr(os, "getgid", lambda: 1000)()),
        "AILAB_BIND_ADDRESS": existing.get("AILAB_BIND_ADDRESS", "127.0.0.1"),
        "AILAB_PORT": existing.get("AILAB_PORT", "8765"),
        "SEMINAR_MAX_FILE_MB": existing.get("SEMINAR_MAX_FILE_MB", "100"),
        "SEMINAR_WATCH_INTERVAL": existing.get("SEMINAR_WATCH_INTERVAL", "5"),
        "TEAMS_TENANT_ID": tenant_id,
        "TEAMS_CLIENT_ID": client_id,
        "TEAMS_CLIENT_SECRET": client_secret,
        "TEAMS_TEAM_ID": team_id,
        "TEAMS_CHANNEL_ID": channel_id,
        "TEAMS_PUBLIC_URL": public_url.rstrip("/"),
        "TEAMS_DELEGATED_SCOPES": existing.get(
            "TEAMS_DELEGATED_SCOPES", "offline_access Files.Read.All User.Read"
        ),
        "TEAMS_POLL_SECONDS": existing.get("TEAMS_POLL_SECONDS", "60"),
        "TEAMS_IMPORT_EXISTING": existing.get("TEAMS_IMPORT_EXISTING", "false"),
        "TEAMS_REQUIRED_TAG": existing.get("TEAMS_REQUIRED_TAG", ""),
    }
    temporary = ENV_PATH.with_suffix(".tmp")
    temporary.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(ENV_PATH)

    for directory in (ROOT / "seminar-data", ROOT / "seminar-inbox", ROOT / "teams-sync-state"):
        directory.mkdir(parents=True, exist_ok=True)

    if not MAP_PATH.exists():
        MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text(json.dumps({"by_teams_user_id": {}, "by_email": {}}, indent=2) + "\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_teams_app.py"),
            "--app-id",
            client_id,
            "--public-url",
            public_url,
        ],
        cwd=ROOT,
        check=True,
    )
    print("\n설정 저장 완료")
    print("1. dist/cbnu-ailab-seminar-teams-app.zip을 세미나 Teams 팀에 추가하세요.")
    print("2. Entra Authentication에서 Allow public client flows를 Yes로 설정하세요.")
    print("3. seminar_service/config/presenter-map.json에 Teams 사용자 ID와 Discord 닉네임을 등록하세요.")
    print("4. 첫 실행에서 안내되는 Microsoft 파일 로그인을 한 번 완료하세요.")
    if os.name == "nt":
        print("5. 이후에는 start-portable.cmd만 실행하면 됩니다.\n")
    else:
        print("5. 이후에는 바탕화면의 AI Lab 세미나 서버 아이콘만 실행하면 됩니다.\n")


if __name__ == "__main__":
    main()
