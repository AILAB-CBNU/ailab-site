#!/usr/bin/env python3
"""Run the website and Teams collector directly from the portable Windows bundle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TOKEN_PATH = ROOT / "teams-sync-state" / "delegated-token.json"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def run_first_setup() -> None:
    if not ENV_PATH.exists():
        subprocess.run([sys.executable, str(ROOT / "server" / "setup.py")], cwd=ROOT, check=True)


def configured_environment(values: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(values)
    env.update(
        {
            "PYTHONUTF8": "1",
            "HOST": values.get("AILAB_BIND_ADDRESS", "127.0.0.1"),
            "PORT": values.get("AILAB_PORT", "8765"),
            "SITE_DIR": str(ROOT / "site"),
            "SEMINAR_DATA_DIR": str(ROOT / "seminar-data"),
            "SEMINAR_INBOX_DIR": str(ROOT / "seminar-inbox"),
            "PRESENTER_MAP_PATH": str(ROOT / "seminar_service" / "config" / "presenter-map.json"),
            "TEAMS_SYNC_STATE_DIR": str(ROOT / "teams-sync-state"),
        }
    )
    return env


def wait_for_health(url: str, processes: list[subprocess.Popen]) -> None:
    for _ in range(40):
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("서비스가 시작 중 종료되었습니다. logs 폴더를 확인하세요.")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok"):
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("40초 안에 웹사이트 상태를 확인하지 못했습니다.")


def main() -> None:
    os.chdir(ROOT)
    for name in ("seminar-data", "seminar-inbox", "teams-sync-state", "logs", "dist"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    run_first_setup()
    values = load_env()
    env = configured_environment(values)

    required = ["TEAMS_TENANT_ID", "TEAMS_CLIENT_ID", "TEAMS_CLIENT_SECRET", "TEAMS_TEAM_ID", "TEAMS_CHANNEL_ID"]
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise RuntimeError("설정이 비어 있습니다: " + ", ".join(missing))
    if not TOKEN_PATH.exists():
        subprocess.run([sys.executable, str(ROOT / "teams_sync" / "device_login.py")], cwd=ROOT, env=env, check=True)

    port = values.get("AILAB_PORT", "8765")
    health_url = f"http://127.0.0.1:{port}/api/health"
    seminar_url = f"http://127.0.0.1:{port}/seminars.html"
    try:
        with urllib.request.urlopen(health_url, timeout=2):
            print(f"이미 실행 중입니다: {seminar_url}")
            webbrowser.open(seminar_url)
            return
    except Exception:
        pass

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    website_log = (ROOT / "logs" / "website.log").open("ab")
    teams_log = (ROOT / "logs" / "teams-sync.log").open("ab")
    processes = [
        subprocess.Popen(
            [sys.executable, str(ROOT / "seminar_service" / "app.py")],
            cwd=ROOT,
            env=env,
            stdout=website_log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        ),
        subprocess.Popen(
            [sys.executable, str(ROOT / "teams_sync" / "app.py")],
            cwd=ROOT,
            env=env,
            stdout=teams_log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        ),
    ]
    try:
        wait_for_health(health_url, processes)
        print(f"AI Lab 세미나 서버가 실행 중입니다: {seminar_url}")
        print("이 창을 닫으면 서버가 종료됩니다. 로그는 logs 폴더에 저장됩니다.")
        webbrowser.open(seminar_url)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("서비스 하나가 종료되었습니다. logs 폴더를 확인하세요.")
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        website_log.close()
        teams_log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise SystemExit(1)
