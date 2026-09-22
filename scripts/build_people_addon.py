#!/usr/bin/env python3
"""Build the people editor update without collecting server uploads or settings."""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path

if __package__:
    from .build_seminar_addon import public_site_file, reject_symlink
else:
    from build_seminar_addon import public_site_file, reject_symlink


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-people-update-20260922.zip"

# Include the seminar backend update as well, so a server can install this
# package without first installing the earlier seminar package.
INCLUDE_FILES = (
    "seminar_service/app.py",
    "discord_sync/__init__.py",
    "discord_sync/app.py",
    "docs/people-profiles.md",
    "docs/seminar-update-20260922.md",
    "docs/discord-setup.md",
)


def source_files(root: Path) -> list[Path]:
    site = root / "site"
    reject_symlink(site, root)
    if not site.is_dir():
        raise FileNotFoundError("The public site/ directory is missing")
    files = []
    for path in sorted(site.rglob("*")):
        reject_symlink(path, root)
        if public_site_file(path, root):
            files.append(path)
    if site / "index.html" not in files:
        raise FileNotFoundError("site/index.html is required")
    for relative in INCLUDE_FILES:
        path = root / relative
        reject_symlink(path, root)
        if not path.is_file():
            raise FileNotFoundError(f"Required update file is missing: {relative}")
        files.append(path)
    return files


def build_bundle(root: Path, output: Path) -> None:
    root = root.resolve()
    files = source_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="people-update-", suffix=".zip.tmp", dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in files:
                reject_symlink(path, root)
                # No top-level wrapper folder: extract beside the existing
                # 06/10 launchers without replacing any server data directory.
                bundle.write(path, path.relative_to(root).as_posix())
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
