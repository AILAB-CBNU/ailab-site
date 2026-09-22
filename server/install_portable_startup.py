#!/usr/bin/env python3
"""Install a per-user Windows Startup shortcut without administrator rights."""

import os
from pathlib import Path


root = Path(__file__).resolve().parents[1]
startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
startup.mkdir(parents=True, exist_ok=True)
launcher = startup / "AI Lab Seminar Server.cmd"
launcher.write_text(
    '@chcp 65001 >nul\r\n@echo off\r\nstart "" /min "' + str(root / "start-portable.cmd") + '"\r\n',
    encoding="utf-8",
)
print(f"Windows 시작 프로그램에 등록했습니다: {launcher}")
