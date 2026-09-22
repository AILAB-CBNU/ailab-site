"""Discord seminar collector. Standard library only; no Docker or pip required."""
from __future__ import annotations
import getpass
import json
import logging
import os
from pathlib import Path
import re
import sys
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Embedded Python and direct script execution must both find the project.
sys.path.insert(0, str(ROOT))
from seminar_service.app import _safe_filename, _clean_text, MAX_FILE_BYTES, IngestError
LOG = logging.getLogger("discord-sync")
STATE = ROOT / "discord-sync-state"
CONFIG = STATE / "config.json"
INBOX = ROOT / "seminar-inbox"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Discord HTTP {status}. Check token, channel access and Message Content Intent.")


class AttachmentError(RuntimeError):
    def __init__(self, status, host):
        self.status = status
        self.host = host
        super().__init__(f"Attachment download HTTP {status} from {host}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, route):
        request = urllib.request.Request("https://discord.com/api/v10" + route, headers={
            "Authorization": "Bot " + self.token,
            "User-Agent": "DiscordBot (https://ailab.cbnu.ac.kr, 1.0)",
        })
        for attempt in range(5):
            try:
                with self.opener.open(request, timeout=30) as response:
                    payload = json.load(response)
                    if response.headers.get("X-RateLimit-Remaining") == "0":
                        time.sleep(max(0, float(response.headers.get("X-RateLimit-Reset-After", "1"))))
                    return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    try:
                        delay = float(json.load(exc).get("retry_after", 5))
                    except (ValueError, TypeError):
                        delay = 5
                    time.sleep(max(1, delay))
                elif exc.code >= 500:
                    time.sleep(2 ** attempt)
                else:
                    raise ApiError(exc.code) from None
        raise RuntimeError("Discord is busy; retry later.")

    def download(self, url, path, budget):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not parsed.path.startswith("/attachments/")):
            raise ValueError("Unexpected attachment URL")
        # Never send the bot token to the CDN. Do not follow redirects.
        size = 0
        request = urllib.request.Request(url, headers={
            "User-Agent": "DiscordBot (https://ailab.cbnu.ac.kr, 1.1)",
        })
        try:
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as exc:
            # Preserve useful diagnostics without exposing signed URLs or tokens.
            raise AttachmentError(exc.code, parsed.hostname) from None
        with response, path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > budget:
                    raise IngestError("Attachment size limit exceeded")
                output.write(chunk)
        if not size:
            raise IngestError("Empty attachment")
        return size


def validate(client, channel):
    app = client.get("/oauth2/applications/@me")
    if not int(app.get("flags", 0)) & ((1 << 18) | (1 << 19)):
        raise RuntimeError("Enable Message Content Intent in the Discord developer portal first.")
    info = client.get(f"/channels/{channel}")
    if info.get("type") not in (0, 5) or not info.get("guild_id"):
        raise RuntimeError("Choose a server text channel (not a forum, thread or DM).")
    client.get(f"/channels/{channel}/messages?limit=1")
    return info


def new_messages(client, channel, cursor):
    rows = {}
    before = None
    while True:
        route = f"/channels/{channel}/messages?limit=100"
        if before:
            route += "&before=" + before
        page = client.get(route)
        if not page:
            break
        for item in page:
            if int(item["id"]) > int(cursor):
                rows[item["id"]] = item
        oldest = min(int(item["id"]) for item in page)
        if oldest <= int(cursor) or len(page) < 100:
            break
        before = str(oldest)
    return sorted(rows.values(), key=lambda item: int(item["id"]))


def queue_message(client, guild, channel, message, inbox=INBOX):
    author = message.get("author", {})
    attachments = message.get("attachments", [])
    if author.get("bot") or message.get("webhook_id") or not attachments:
        return False
    message_id = message["id"]
    base = f"discord-{channel}-{message_id}"
    manifest = inbox / (base + ".json")
    if manifest.exists() or (inbox / ".processed" / manifest.name).exists():
        return False
    names = [_safe_filename(a["filename"]) for a in attachments]
    if sum(int(a.get("size", 0)) for a in attachments) > MAX_FILE_BYTES:
        raise IngestError("Attachment size limit exceeded")
    try:
        member = client.get(f"/guilds/{guild}/members/{author['id']}")
    except ApiError as exc:
        if exc.status != 404:
            raise
        member = {}
    presenter = member.get("nick") or author.get("global_name") or author.get("username")
    folder = inbox / base
    folder.mkdir(parents=True, exist_ok=True)
    files, total = [], 0
    for index, (attachment, name) in enumerate(zip(attachments, names)):
        destination = folder / str(index)
        part = destination.with_suffix(".part")
        try:
            total += client.download(attachment["url"], part, MAX_FILE_BYTES - total)
            part.replace(destination)
        finally:
            part.unlink(missing_ok=True)
        files.append({"name": name, "path": f"{base}/{index}"})
    content = message.get("content", "").strip()
    title = (content.splitlines()[0] if content else Path(names[0]).stem)
    payload = {
        "source": "discord",
        "source_message_id": f"discord:{guild}:{channel}:{message_id}",
        "presenter_discord": _clean_text(presenter, "presenter", 80),
        "uploaded_at": message["timestamp"],
        "title": _clean_text(title[:170], "title", 180),
        "summary": _clean_text(content[:950], "summary", 1000),
        "files": files,
    }
    # Commit only after every file is complete. Existing website watcher ingests it.
    atomic_json(manifest, payload)
    return True


def setup():
    print("Discord setup. Token input is hidden. Do not paste it into chat.")
    token = getpass.getpass("Bot token: ").strip()
    raw = input("Seminar channel ID or channel URL: ").strip().rstrip("/")
    channel = raw.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9]{15,22}", channel):
        raise RuntimeError("Invalid channel ID")
    client = Client(token)
    info = validate(client, channel)
    latest = client.get(f"/channels/{channel}/messages?limit=1")
    cursor = latest[0]["id"] if latest else "0"
    # Establish the starting point now, before the first test upload.
    atomic_json(STATE / f"{channel}.json", {"cursor": cursor})
    atomic_json(CONFIG, {"token": token, "channel": channel, "guild": info["guild_id"]})
    CONFIG.chmod(0o600)
    print("Setup complete. Start 10-START-DISCORD-SYNC.bat, then upload a NEW file.")


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(ROOT / "logs/discord-sync.log", encoding="utf-8")])
    if "--setup" in sys.argv:
        setup()
        return
    if not CONFIG.exists():
        raise RuntimeError("Run 09-SETUP-DISCORD.bat first.")
    # Hold a local socket for the process lifetime to prevent concurrent writers.
    instance_lock = socket.socket()
    try:
        instance_lock.bind(("127.0.0.1", 48761))
    except OSError:
        raise RuntimeError("Another collector is running (local port 48761 is in use).") from None
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    client = Client(config["token"])
    channel = config["channel"]
    info = validate(client, channel)
    if info["guild_id"] != config["guild"]:
        raise RuntimeError("Channel server mismatch")
    checkpoint = STATE / f"{channel}.json"
    if not checkpoint.exists():
        raise RuntimeError("Missing checkpoint; run setup again to choose a new starting point.")
    cursor = json.loads(checkpoint.read_text(encoding="utf-8"))["cursor"]
    LOG.info("Collector ready for channel %s. Website must run separately. Checking every 15 seconds.", channel)
    while True:
        try:
            for message in new_messages(client, channel, cursor):
                try:
                    queued = queue_message(client, config["guild"], channel, message)
                except IngestError as exc:
                    # Persistent rejection record; an invalid file must not block subsequent uploads.
                    atomic_json(STATE / ("rejected-" + message["id"] + ".json"), {"id": message["id"], "reason": str(exc)})
                    LOG.warning("Rejected message %s: unsupported, empty or oversized file. See discord-sync-state.", message["id"])
                else:
                    if queued:
                        LOG.info("Queued message %s for website ingestion", message["id"])
                cursor = message["id"]
                atomic_json(checkpoint, {"cursor": cursor})
        except AttachmentError as exc:
            LOG.warning("Attachment download failed: HTTP %s, host=%s; checkpoint retained. "
                        "Retrying with freshly fetched message URLs in 15 seconds.", exc.status, exc.host)
        except ApiError as exc:
            if exc.status in (401, 403):
                raise
            LOG.warning("Discord request failed; retrying in 15 seconds (HTTP %s).", exc.status)
        except Exception as exc:
            # Never log token, signed URL, response content or user message.
            LOG.warning("Collection failed (%s); checkpoint retained, retrying in 15 seconds.", type(exc).__name__)
        time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Collector stopped.")
    except Exception as exc:
        print("Collector stopped:", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        sys.exit(1)
