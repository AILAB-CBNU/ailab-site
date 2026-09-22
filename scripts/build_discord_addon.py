#!/usr/bin/env python3
"""Build the Discord modal update, preserving the existing server's private state."""

from __future__ import annotations

import hashlib
from pathlib import Path

if __package__:
    from . import build_people_addon as people_build
else:
    import build_people_addon as people_build


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-discord-form-update-20260922.zip"

# The common allowlist is kept in build_seminar_addon so every addon ships a
# complete current Discord runtime, including Gateway/vendor dependencies.
DISCORD_RUNTIME_FILES = people_build.DISCORD_RUNTIME_FILES
INCLUDE_FILES = people_build.INCLUDE_FILES


def build_bundle(root: Path, output: Path) -> None:
    people_build.build_bundle(root, output)


def main() -> None:
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
