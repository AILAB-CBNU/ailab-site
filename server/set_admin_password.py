#!/usr/bin/env python3
"""Set or replace the website administrator password locally."""

from __future__ import annotations

import getpass
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seminar_service import app  # noqa: E402


def main() -> None:
    app._ensure_layout()
    print("CBNU AI Lab website administrator password setup")
    print("Use at least 12 characters. The password is not displayed while typing.")
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("입력한 비밀번호가 서로 다릅니다.")
    app.configure_admin_password(first)
    print("Administrator password saved.")
    print("Open: https://ailab.cbnu.ac.kr/admin.html")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
