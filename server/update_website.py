"""Update only public site files from a pinned commit of AILAB-CBNU/ailab-site."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPO = 'AILAB-CBNU/ailab-site'
MAX_DOWNLOAD = 30 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
REQUIRED = ('index.html', 'people.html', 'publications.html', 'news.html',
            'js/main.js', 'js/data.js', 'css/styles.css')


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'CBNU-AILab-SiteUpdater/1.0', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Download exceeds size limit')
    return data


def unpack_site(data: bytes, stage: Path, revision: str) -> None:
    total = 0
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            parts = PurePosixPath(entry.filename).parts
            # All archive paths must belong to this exact commit; never extract code or state.
            if not parts or parts[0] != 'ailab-site-' + revision:
                raise ValueError('Unexpected archive root')
            if len(parts) < 3 or parts[1] != 'site' or entry.is_dir():
                continue
            relative = parts[2:]
            if any(p in ('.', '..') or '\\' in p or ':' in p or p.endswith((' ', '.')) for p in relative):
                raise ValueError('Unsafe site path')
            if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Symlink in website archive')
            normalized = '/'.join(relative).lower()
            if normalized in seen:
                raise ValueError('Duplicate site path')
            seen.add(normalized)
            total += entry.file_size
            if total > MAX_EXPANDED:
                raise ValueError('Expanded archive exceeds size limit')
            destination = stage.joinpath(*relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(entry))
    if not all((stage / name).is_file() for name in REQUIRED):
        raise ValueError('Incomplete website archive')


def update(root: Path = ROOT, fetch=download) -> bool:
    if not (root / 'site/index.html').is_file() or not (root / 'server/website_only.py').is_file():
        raise ValueError('Run inside the existing portable website project')
    state = root / 'website-update-state'
    state.mkdir(exist_ok=True)
    # Both the scheduler and the manual button use this OS-released file lock.
    with (state / 'update.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            logging.info('Another update is running; skipped')
            return False
        revision = json.loads(fetch(f'https://api.github.com/repos/{REPO}/commits/main'))['sha']
        if not re.fullmatch('[0-9a-f]{40}', revision):
            raise ValueError('Invalid commit ID')
        marker = state / 'deployed-commit.txt'
        if marker.exists() and marker.read_text().strip() == revision:
            logging.info('Already current: %s', revision[:12])
            return False
        data = fetch(f'https://codeload.github.com/{REPO}/zip/{revision}')
        with tempfile.TemporaryDirectory(prefix='staging-', dir=state) as temporary:
            stage = Path(temporary) / 'site'
            stage.mkdir()
            unpack_site(data, stage, revision)
            backup = state / ('backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            live = root / 'site'
            live.rename(backup)
            try:
                stage.rename(live)
            except BaseException:
                backup.rename(live)
                raise
        marker_tmp = state / 'deployed-commit.tmp'
        marker_tmp.write_text(revision + '\n', encoding='ascii')
        marker_tmp.replace(marker)
        logging.info('Updated to %s. Previous site: %s', revision, backup)
        # Keep the three most recent backups created by this updater.
        backups = sorted(p for p in state.glob('backup-*') if re.fullmatch(r'backup-\d{8}T\d{12}Z', p.name) and p.is_dir() and not p.is_symlink())
        for old in backups[:-3]:
            shutil.rmtree(old)
        return True


def task_name() -> str:
    suffix = hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
    return 'CBNU-AILab-Website-Update-' + suffix


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def configure_task(remove: bool = False) -> None:
    if os.name != 'nt':
        raise RuntimeError('Task setup requires Windows')
    name = ps_quote(task_name())
    if remove:
        code = f"$ErrorActionPreference='Stop'; Unregister-ScheduledTask -TaskName {name} -Confirm:$false"
    else:
        # Use the exact embedded Python executable; no Git or Python installation needed.
        executable = ps_quote(sys.executable)
        arguments = ps_quote('"' + str(Path(__file__).resolve()) + '"')
        directory = ps_quote(str(ROOT))
        code = f"""$ErrorActionPreference='Stop'
$a = New-ScheduledTaskAction -Execute {executable} -Argument {arguments} -WorkingDirectory {directory}
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$l = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$p = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName {name} -Action $a -Trigger @($t,$l) -Principal $p -Settings $s -Force | Out-Null
"""
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code], check=True)
    print(('Removed: ' if remove else 'Installed: ') + task_name())
    if not remove:
        print('Checks main every 5 minutes while this Windows user is logged in (screen lock is OK).')


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', action='store_true')
    group.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    (ROOT / 'logs').mkdir(exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.StreamHandler(), RotatingFileHandler(ROOT / 'logs/website-update.log', maxBytes=1024*1024, backupCount=2, encoding='utf-8')])
    try:
        if args.uninstall:
            configure_task(remove=True)
        else:
            update()
            if args.install:
                configure_task()
        return 0
    except Exception:
        logging.exception('Update failed. Check logs/website-update.log')
        return 1


if __name__ == '__main__':
    sys.exit(main())
