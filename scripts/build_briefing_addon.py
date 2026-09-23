"""Cumulative server update. Credentials, conversations and task ledgers stay local."""
import hashlib
from pathlib import Path

if __package__:
    from . import build_lab_addon as lab
else:
    import build_lab_addon as lab

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-briefing-update-20260923.zip"
INCLUDE_FILES = lab.INCLUDE_FILES + ("14-SETUP-LAB-BRIEFING.bat", "docs/lab-briefing.md")


def build_bundle(root, output):
    lab.people_build.seminar_build.build_bundle(root, output, INCLUDE_FILES)


if __name__ == "__main__":
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
