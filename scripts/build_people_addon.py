#!/usr/bin/env python3
"""Build the people editor update without collecting server uploads or settings."""

from __future__ import annotations

import hashlib
from pathlib import Path

if __package__:
    from . import build_seminar_addon as seminar_build
else:
    import build_seminar_addon as seminar_build

DISCORD_RUNTIME_FILES = seminar_build.DISCORD_RUNTIME_FILES
public_site_file = seminar_build.public_site_file
reject_symlink = seminar_build.reject_symlink


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-people-update-20260922.zip"

# Include the seminar backend update as well, so a server can install this
# package without first installing the earlier seminar package.
INCLUDE_FILES = seminar_build.INCLUDE_FILES + (
    "docs/people-profiles.md",
)


def source_files(root: Path) -> list[Path]:
    return seminar_build.source_files(root, INCLUDE_FILES)


def build_bundle(root: Path, output: Path) -> None:
    seminar_build.build_bundle(root, output, INCLUDE_FILES)


def main() -> None:
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
