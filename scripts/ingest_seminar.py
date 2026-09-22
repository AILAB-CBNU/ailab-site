#!/usr/bin/env python3
"""Upload one or more local seminar files to the running archive service."""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--presenter", help="디스코드 서버 닉네임")
    parser.add_argument("--teams-user-id")
    parser.add_argument("--teams-email")
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--uploaded-at", default=datetime.now().astimezone().isoformat(timespec="seconds"))
    parser.add_argument("--summary", default="")
    parser.add_argument("--url", default=os.environ.get("SEMINAR_SERVICE_URL", "http://127.0.0.1:8765"))
    args = parser.parse_args()
    token = os.environ.get("SEMINAR_UPLOAD_TOKEN", "")
    if not token:
        parser.error("SEMINAR_UPLOAD_TOKEN 환경변수가 필요합니다.")
    payload = {
        "source": "hermes-cli",
        "source_message_id": args.message_id,
        "source_user_id": args.teams_user_id,
        "source_user_email": args.teams_email,
        "presenter_discord": args.presenter,
        "title": args.title,
        "summary": args.summary,
        "uploaded_at": args.uploaded_at,
        "files": [],
    }
    for path in args.files:
        data = path.read_bytes()
        payload["files"].append({"name": path.name, "content_base64": base64.b64encode(data).decode("ascii")})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        args.url.rstrip("/") + "/api/ingest",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
