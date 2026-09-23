#!/usr/bin/env python3
"""Cumulative lab website update, excluding server state and uploaded photos."""
import hashlib
from pathlib import Path

if __package__:
    from . import build_people_addon as people_build
else:
    import build_people_addon as people_build

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-lab-update-20260923.zip"
INCLUDE_FILES = people_build.INCLUDE_FILES + ("docs/lab-update-20260923.md",)


def build_bundle(root, output):
    people_build.seminar_build.build_bundle(root, output, INCLUDE_FILES)


if __name__ == "__main__":
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
