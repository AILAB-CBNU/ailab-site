#!/usr/bin/env python3
"""Build the seminar update without packaging server data, settings, or runtimes."""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "ailab-seminar-update-20260922.zip"

# All addon builders share this complete runtime dependency list. A rebuilt
# older addon must not ship a newer app.py without its Gateway/modal modules.
DISCORD_RUNTIME_FILES = (
    "discord_sync/__init__.py",
    "discord_sync/app.py",
    "discord_sync/interactions.py",
    "discord_sync/gateway.py",
    "discord_sync/vendor/__init__.py",
    "discord_sync/vendor/README.md",
    "discord_sync/vendor/LICENSE.websocket-client",
    "discord_sync/vendor/websocket/__init__.py",
    "discord_sync/vendor/websocket/_abnf.py",
    "discord_sync/vendor/websocket/_app.py",
    "discord_sync/vendor/websocket/_cookiejar.py",
    "discord_sync/vendor/websocket/_core.py",
    "discord_sync/vendor/websocket/_dispatcher.py",
    "discord_sync/vendor/websocket/_exceptions.py",
    "discord_sync/vendor/websocket/_handshake.py",
    "discord_sync/vendor/websocket/_http.py",
    "discord_sync/vendor/websocket/_logging.py",
    "discord_sync/vendor/websocket/_socket.py",
    "discord_sync/vendor/websocket/_ssl_compat.py",
    "discord_sync/vendor/websocket/_url.py",
    "discord_sync/vendor/websocket/_utils.py",
    "discord_sync/vendor/websocket/py.typed",
)
# Only these backend modules and documents may leave the development checkout.
# Do not replace this allowlist with recursive package-directory inclusion.
INCLUDE_FILES = DISCORD_RUNTIME_FILES + (
    "seminar_service/app.py",
    "docs/discord-setup.md",
    "docs/seminar-update-20260922.md",
    "docs/discord-form-update-20260922.md",
)
PUBLIC_SITE_SUFFIXES = frozenset({
    ".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".ico", ".avif", ".woff", ".woff2", ".ttf", ".otf", ".md",
})
PRIVATE_DIRECTORIES = frozenset({
    "__pycache__", "node_modules", "runtime", "config", "logs", "dist",
    "seminar-data", "seminar-inbox", "website-update-state", "caddy-data",
    "caddy-config", "keys",
})


def reject_symlink(path: Path, root: Path) -> None:
    """Reject both file links and a link in any parent within the source tree."""
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Symbolic links cannot be packaged: {current.relative_to(root)}")
        if current == current.parent:
            raise ValueError("Package source must be inside the project directory")
        current = current.parent


def public_site_file(path: Path, root: Path) -> bool:
    parts = path.relative_to(root / "site").parts
    if parts == ("data", "projects.json"):
        return path.is_file()
    if any(part.startswith(".") or part.lower() in PRIVATE_DIRECTORIES
           or part.lower().endswith("-sync-state") for part in parts):
        return False
    return path.is_file() and path.suffix.lower() in PUBLIC_SITE_SUFFIXES


def source_files(root: Path, include_files: tuple[str, ...] | None = None) -> list[Path]:
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
    for relative in INCLUDE_FILES if include_files is None else include_files:
        path = root / relative
        reject_symlink(path, root)
        if not path.is_file():
            raise FileNotFoundError(f"Required update file is missing: {relative}")
        files.append(path)
    return files


def build_bundle(root: Path, output: Path, include_files: tuple[str, ...] | None = None) -> None:
    root = root.resolve()
    files = source_files(root, include_files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="seminar-update-", suffix=".zip.tmp", dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in files:
                # Recheck just before reading. There is intentionally no enclosing
                # directory: users extract beside the existing 06/10 launchers.
                reject_symlink(path, root)
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
