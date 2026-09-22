#!/usr/bin/env python3
"""Build a copy-and-run Windows x64 bundle with the official embedded Python."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.15"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
CADDY_VERSION = "2.11.4"
CADDY_URL = f"https://github.com/caddyserver/caddy/releases/download/v{CADDY_VERSION}/caddy_{CADDY_VERSION}_windows_amd64.zip"
CADDY_SHA512 = "cd5ccfd86a4b40732cf715890d0dca5bf3f63adefec5a7914de85adf240c60ce7e5d2791631b88ef9758e46b23bb1730e020b9c5d696889740b284ffd4788e35"
OUTPUT = ROOT / "dist" / "cbnu-ailab-windows-portable.zip"
PREFIX = "ailab-site-v1"

INCLUDE_DIRS = (
    "site",
    "seminar_service",
    "teams_sync",
    "discord_sync",
    "teams-app",
    "server",
    "docs",
)
INCLUDE_FILES = (
    "README.md",
    ".env.example",
    "Caddyfile",
    "01-ALLOW-PORT-80-AS-ADMIN.bat",
    "02-START-WEBSITE.bat",
    "03-CHECK-WEBSITE.bat",
    "04-START-FULL-SERVICE.bat",
    "05-ALLOW-HTTPS-AS-ADMIN.bat",
    "06-START-HTTPS-WEBSITE.bat",
    "07-CHECK-HTTPS.bat",
    "08-SET-ADMIN-PASSWORD.bat",
    "09-SETUP-DISCORD.bat",
    "10-START-DISCORD-SYNC.bat",
    "11-INSTALL-AUTO-UPDATE.bat",
    "12-UPDATE-WEBSITE-NOW.bat",
    "13-STOP-AUTO-UPDATE.bat",
    "scripts/build_teams_app.py",
    "scripts/ingest_seminar.py",
)


def download_runtime(target: Path) -> None:
    with urllib.request.urlopen(PYTHON_URL, timeout=60) as response, target.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        raise RuntimeError(f"Python runtime checksum mismatch: {digest}")


def download_caddy(target: Path) -> None:
    with urllib.request.urlopen(CADDY_URL, timeout=60) as response, target.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    digest = hashlib.sha512(target.read_bytes()).hexdigest()
    if digest != CADDY_SHA512:
        raise RuntimeError(f"Caddy checksum mismatch: {digest}")


def allowed(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path.is_symlink():
        return False
    if relative.parts[:2] == ("seminar_service", "config"):
        return relative.as_posix() == "seminar_service/config/presenter-map.example.json"
    if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
        return False
    return path.suffix.lower() not in {".pyc", ".log", ".key", ".pem", ".pfx", ".p12", ".db", ".sqlite", ".bak"}


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        runtime_zip = Path(temporary) / "python-embed.zip"
        caddy_zip = Path(temporary) / "caddy-windows.zip"
        download_runtime(runtime_zip)
        download_caddy(caddy_zip)
        with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            # Always create fresh defaults; never package a running server's data.
            bundle.writestr(f"{PREFIX}/seminar-data/index.json", "[]\n")
            bundle.writestr(f"{PREFIX}/seminar_service/config/presenter-map.json", '{"by_teams_user_id":{},"by_email":{}}\n')
            bundle.write(ROOT / "seminar-inbox/README.md", f"{PREFIX}/seminar-inbox/README.md")
            for directory in INCLUDE_DIRS:
                for path in sorted((ROOT / directory).rglob("*")):
                    if path.is_file() and allowed(path):
                        bundle.write(path, f"{PREFIX}/{path.relative_to(ROOT).as_posix()}")
            for relative in INCLUDE_FILES:
                path = ROOT / relative
                if path.suffix.lower() == ".bat":
                    content = path.read_text(encoding="ascii").replace("\r\n", "\n").replace("\n", "\r\n")
                    bundle.writestr(f"{PREFIX}/{relative}", content.encode("ascii"))
                else:
                    bundle.write(path, f"{PREFIX}/{relative}")
            with zipfile.ZipFile(runtime_zip) as runtime:
                for member in runtime.infolist():
                    if not member.is_dir():
                        content = runtime.read(member)
                        if member.filename == "python313._pth":
                            content = (
                                "python313.zip\r\n.\r\n../..\r\n../../server\r\n../../teams_sync\r\n"
                                "../../seminar_service\r\n../../scripts\r\n\r\n#import site\r\n"
                            ).encode("ascii")
                        bundle.writestr(f"{PREFIX}/runtime/python/{member.filename}", content)
            with zipfile.ZipFile(caddy_zip) as caddy:
                for member in caddy.infolist():
                    if not member.is_dir():
                        bundle.writestr(f"{PREFIX}/runtime/caddy/{member.filename}", caddy.read(member))
            instructions = (
                "CBNU AI Lab 세미나 서버 — Windows 무설치 버전\r\n"
                "\r\n"
                "1. 이 폴더를 C:\\AI-Lab 같은 쓰기 가능한 위치에 둡니다.\r\n"
                "2. 01-ALLOW-PORT-80-AS-ADMIN.bat를 우클릭하여 관리자 권한으로 한 번 실행합니다.\r\n"
                "3. 02-START-WEBSITE.bat를 더블클릭합니다. Teams 설정 없이 80번 포트에서 바로 실행됩니다.\r\n"
                "4. 03-CHECK-WEBSITE.bat로 localhost와 도메인 응답을 확인합니다.\r\n"
                "\r\n"
                "[HTTPS로 공개할 때]\r\n"
                "5. 실행 중인 02번 검은 창을 닫습니다.\r\n"
                "6. 05-ALLOW-HTTPS-AS-ADMIN.bat를 우클릭하여 관리자 권한으로 한 번 실행합니다.\r\n"
                "7. 06-START-HTTPS-WEBSITE.bat를 더블클릭합니다. 인증서는 자동 발급·갱신됩니다.\r\n"
                "8. 07-CHECK-HTTPS.bat로 https://ailab.cbnu.ac.kr 응답을 확인합니다.\r\n"
                "\r\n"
                "[관리자 페이지]\r\n"
                "9. 08-SET-ADMIN-PASSWORD.bat를 실행해 12자 이상의 관리자 비밀번호를 설정합니다.\r\n"
                "10. https://ailab.cbnu.ac.kr/admin.html 에 로그인합니다.\r\n"
                "\r\n"
                "[나중에 Teams 자동 수집까지 연결할 때]\r\n"
                "11. 04-START-FULL-SERVICE.bat를 더블클릭합니다.\r\n"
                "12. 최초 한 번 Entra secret, 팀/채널 ID, 공개 HTTPS 주소를 입력합니다.\r\n"
                "13. 안내되는 Microsoft 파일 로그인을 완료합니다.\r\n"
                "14. 생성된 dist\\cbnu-ailab-seminar-teams-app.zip을 Teams 세미나 팀에 설치합니다.\r\n"
                "\r\n"
                "Docker, Hyper-V, 시스템 Python 설치가 필요하지 않습니다.\r\n"
                "로그는 logs 폴더, 세미나 자료는 seminar-data 폴더에 저장됩니다.\r\n"
            )
            bundle.writestr(f"{PREFIX}/START-HERE.txt", instructions.encode("utf-8-sig"))
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
