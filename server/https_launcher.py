#!/usr/bin/env python3
"""Run the portable website behind Caddy with automatic public HTTPS."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CADDY = ROOT / "runtime" / "caddy" / "caddy.exe"
CADDYFILE = ROOT / "Caddyfile"
HTTPS_URL = "https://ailab.cbnu.ac.kr/"


def status(message: str) -> None:
    print(message, flush=True)


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def wait_for_url(url: str, processes: list[subprocess.Popen[bytes]], timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            return False
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main() -> None:
    os.chdir(ROOT)
    status("[1/5] Checking HTTPS files and ports...")
    for name in ("seminar-data", "seminar-inbox", "logs", "caddy-data", "caddy-config"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)

    if not CADDY.is_file():
        raise RuntimeError("runtime\\caddy\\caddy.exe 파일이 없습니다.")
    if not CADDYFILE.is_file():
        raise RuntimeError("Caddyfile 파일이 없습니다.")

    occupied = [str(port) for port in (80, 443, 8765) if port_is_open(port)]
    if occupied:
        raise RuntimeError(
            "이미 사용 중인 포트가 있습니다: "
            + ", ".join(occupied)
            + ". 기존 웹사이트 검은 창을 닫은 뒤 다시 실행하세요."
        )

    env = os.environ.copy()
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            "WEBSITE_HOST": "127.0.0.1",
            "WEBSITE_PORT": "8765",
            "NO_BROWSER": "1",
            "XDG_DATA_HOME": str(ROOT / "caddy-data"),
            "XDG_CONFIG_HOME": str(ROOT / "caddy-config"),
        }
    )

    backend_log = (ROOT / "logs" / "website-https-backend.log").open("ab")
    status("[2/5] Starting the website on 127.0.0.1:8765...")
    backend = subprocess.Popen(
        [sys.executable, str(ROOT / "server" / "website_only.py")],
        cwd=ROOT,
        env=env,
        stdout=backend_log,
        stderr=subprocess.STDOUT,
    )
    processes: list[subprocess.Popen[bytes]] = [backend]

    try:
        if not wait_for_url("http://127.0.0.1:8765/api/health", processes, 20):
            raise RuntimeError("내부 웹사이트가 20초 안에 시작되지 않았습니다. logs 폴더를 확인하세요.")

        status("[3/5] Website backend is ready.")
        status("[4/5] Starting Caddy on ports 80 and 443...")
        caddy = subprocess.Popen(
            [str(CADDY), "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
            cwd=ROOT,
            env=env,
        )
        processes.append(caddy)
        status("[5/5] Requesting or loading the HTTPS certificate. This can take about one minute.")

        if not wait_for_url(HTTPS_URL, processes, 90):
            if caddy.poll() is not None:
                raise RuntimeError("Caddy가 종료되었습니다. 위 오류 메시지를 확인하세요.")
            status("Local HTTPS verification is still pending. Run 07-CHECK-HTTPS.bat to check again.")
        else:
            status(f"HTTPS is running: {HTTPS_URL}")
            webbrowser.open(HTTPS_URL)

        status("Keep this window open. Closing it stops the HTTPS website.")
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("웹사이트 또는 Caddy 프로세스가 종료되었습니다.")
    except KeyboardInterrupt:
        status("\nStopping the HTTPS website.")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        backend_log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise SystemExit(1)
