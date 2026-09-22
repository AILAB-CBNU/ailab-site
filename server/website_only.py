#!/usr/bin/env python3
"""Run only the public website on Windows port 80, without Teams setup."""

from __future__ import annotations

import os
import runpy
import threading
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_optional_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    os.chdir(ROOT)
    for name in ("seminar-data", "seminar-inbox", "logs"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    load_optional_env()
    host = os.environ.get("WEBSITE_HOST", "0.0.0.0")
    port = os.environ.get("WEBSITE_PORT", "80")
    os.environ.update(
        {
            "PYTHONUTF8": "1",
            "HOST": host,
            "PORT": port,
            "SITE_DIR": str(ROOT / "site"),
            "SEMINAR_DATA_DIR": str(ROOT / "seminar-data"),
            "SEMINAR_INBOX_DIR": str(ROOT / "seminar-inbox"),
            "PRESENTER_MAP_PATH": str(ROOT / "seminar_service" / "config" / "presenter-map.json"),
        }
    )
    print(f"AI Lab 홈페이지를 {host}:{port}에서 시작합니다.")
    print(f"로컬 확인: http://localhost:{port}/" if port != "80" else "로컬 확인: http://localhost/")
    print("도메인 확인: http://ailab.cbnu.ac.kr/")
    print("이 창을 닫으면 웹 서버가 종료됩니다.\n")
    if os.environ.get("NO_BROWSER", "").lower() not in {"1", "true", "yes"}:
        local_url = f"http://localhost:{port}/" if port != "80" else "http://localhost/"
        threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    runpy.run_path(str(ROOT / "seminar_service" / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
