"""Latest lab content plus cumulative server updates, excluding runtime data."""
import hashlib
from pathlib import Path

if __package__:
    from . import build_briefing_addon as briefing
else:
    import build_briefing_addon as briefing

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-research-update-20261002.zip"
INCLUDE_FILES = briefing.INCLUDE_FILES + ("docs/research-update-20261002.md",)


def build_bundle(root, output):
    briefing.lab.people_build.seminar_build.build_bundle(root, output, INCLUDE_FILES)


if __name__ == "__main__":
    build_bundle(ROOT, OUTPUT)
    print(OUTPUT)
    print(f"size={OUTPUT.stat().st_size} sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
