#!/usr/bin/env python3
"""Build the Teams RSC app package for one public website URL."""

import argparse
import json
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "teams-app" / "manifest.template.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", required=True, help="Microsoft Entra application (client) ID")
    parser.add_argument("--public-url", required=True, help="Public HTTPS origin, without a trailing slash")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "cbnu-ailab-seminar-teams-app.zip")
    args = parser.parse_args()

    try:
        uuid.UUID(args.app_id)
    except ValueError as exc:
        parser.error(f"--app-id is not a UUID: {exc}")
    public_url = args.public_url.rstrip("/")
    parsed = urlsplit(public_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        parser.error("--public-url must be an HTTPS origin such as https://seminar.example.ac.kr")

    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    def replace(value):
        if isinstance(value, str):
            return value.replace("__APP_ID__", args.app_id).replace("__PUBLIC_URL__", public_url).replace(
                "__PUBLIC_DOMAIN__", parsed.hostname
            )
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    manifest = replace(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        package.write(ROOT / "teams-app" / "color.png", "color.png")
        package.write(ROOT / "teams-app" / "outline.png", "outline.png")
    print(args.output)


if __name__ == "__main__":
    main()
