#!/usr/bin/env python3
"""Complete the one-time delegated Microsoft device login for channel files."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from . import app
except ImportError:
    import app


def post_form(url: str, values: dict[str, str]) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> None:
    if not app.TENANT_ID or not app.CLIENT_ID:
        raise SystemExit("TEAMS_TENANT_ID와 TEAMS_CLIENT_ID가 필요합니다.")
    tenant = urllib.parse.quote(app.TENANT_ID, safe="")
    device_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    status, device = post_form(device_url, {"client_id": app.CLIENT_ID, "scope": app.DELEGATED_SCOPES})
    if status >= 400:
        raise SystemExit(device.get("error_description") or str(device))

    print("\nTeams 첨부 파일을 읽을 연구실 계정으로 최초 한 번 로그인하세요.")
    print(device.get("message") or f"{device['verification_uri']} 에서 코드 {device['user_code']} 입력")
    print("로그인을 기다리고 있습니다...\n", flush=True)
    interval = max(5, int(device.get("interval", 5)))
    deadline = time.time() + int(device.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        status, token = post_form(
            token_url,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": app.CLIENT_ID,
                "device_code": str(device["device_code"]),
            },
        )
        if status < 400 and token.get("access_token"):
            token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
            app._atomic_json(app.DELEGATED_TOKEN_PATH, token)
            app.DELEGATED_TOKEN_PATH.chmod(0o600)
            print("Teams 파일 로그인이 저장되었습니다.")
            return
        error = token.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise SystemExit(token.get("error_description") or str(token))
    raise SystemExit("로그인 시간이 만료되었습니다. 다시 실행하세요.")


if __name__ == "__main__":
    main()
