"""Discord seminar collector and forms. Bundled dependencies; no pip required."""
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
from datetime import date
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Embedded Python and direct script execution must both find the project.
sys.path.insert(0, str(ROOT))
# The Windows launcher runs this file directly. Keep one module identity when
# the interaction worker imports our validation and ingestion helpers.
if __name__ == "__main__":
    sys.modules["discord_sync.app"] = sys.modules[__name__]
from seminar_service.app import _safe_filename, _clean_text, MAX_FILE_BYTES, IngestError
LOG = logging.getLogger("discord-sync")
STATE = ROOT / "discord-sync-state"
CONFIG = STATE / "config.json"
INBOX = ROOT / "seminar-inbox"
SEMINAR_HEADINGS = {"# 세미나", "#세미나"}


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

    def request(self, method, route, payload=None, *, timeout=30, retries=5, authenticated=True):
        headers = {"User-Agent": "DiscordBot (https://ailab.cbnu.ac.kr, 1.2)"}
        if authenticated:
            headers["Authorization"] = "Bot " + self.token
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("https://discord.com/api/v10" + route,
                                         data=body, headers=headers, method=method)
        for attempt in range(retries):
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    content = response.read()
                    return json.loads(content) if content else None
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt + 1 < retries:
                    try:
                        delay = float(json.load(exc).get("retry_after", 5))
                    except (ValueError, TypeError):
                        delay = 5
                    time.sleep(max(1, min(60, delay)))
                elif exc.code >= 500 and attempt + 1 < retries:
                    time.sleep(2 ** attempt)
                else:
                    raise ApiError(exc.code) from None
        raise RuntimeError("Discord is busy; retry later.")

    def get(self, route):
        return self.request("GET", route)

    def post(self, route, payload, **options):
        return self.request("POST", route, payload, **options)

    def patch(self, route, payload, **options):
        return self.request("PATCH", route, payload, **options)

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
    if app.get("interactions_endpoint_url"):
        raise RuntimeError("Clear Interactions Endpoint URL in the Discord developer portal to enable Gateway forms.")
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


def parse_seminar_message(content):
    """Accept the published template only; never guess a title from a filename."""
    if not isinstance(content, str):
        raise IngestError("FORMAT_REQUIRED: # 세미나와 제목, 발표일, 요약을 작성하세요.")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines or lines[0] not in SEMINAR_HEADINGS:
        raise IngestError("FORMAT_REQUIRED: 첫 줄은 # 세미나여야 합니다.")
    fields = {}
    for line in lines[1:]:
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or key not in {"제목", "발표일", "요약"} or key in fields:
            raise IngestError("FORMAT_FIELDS: 제목, 발표일, 요약을 각각 한 줄씩 작성하세요.")
        fields[key] = value.strip()
    if set(fields) != {"제목", "발표일", "요약"} or not all(fields.values()):
        raise IngestError("FORMAT_FIELDS: 제목, 발표일, 요약은 모두 필수입니다.")
    return validate_seminar_fields(fields["제목"], fields["발표일"], fields["요약"])


def validate_seminar_fields(title, presented_on, summary):
    """Validate both the one-line message template and the native modal."""
    title = _clean_text(title, "title", 180)
    summary = _clean_text(summary, "summary", 1000)
    if not title or not summary:
        raise IngestError("FORMAT_FIELDS: 제목과 요약은 비어 있을 수 없습니다.")
    if not isinstance(presented_on, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", presented_on):
        raise IngestError("FORMAT_DATE: 발표일은 YYYY-MM-DD 형식이어야 합니다.")
    try:
        date.fromisoformat(presented_on)
    except ValueError:
        raise IngestError("FORMAT_DATE: 실제 달력에 있는 발표일을 입력하세요.") from None
    return {"title": title, "summary": summary, "presented_on": presented_on}


def validate_attachments(attachments):
    if not isinstance(attachments, list) or not attachments:
        raise IngestError("FORMAT_ATTACHMENT: 같은 메시지에 발표 자료를 첨부하세요.")
    if len(attachments) > 10:
        raise IngestError("FORMAT_ATTACHMENT: 한 메시지에는 파일을 10개까지 첨부하세요.")
    names, total = [], 0
    for attachment in attachments:
        if not isinstance(attachment, dict):
            raise IngestError("FORMAT_ATTACHMENT: 올바른 첨부파일이 필요합니다.")
        names.append(_safe_filename(attachment.get("filename")))
        size = attachment.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise IngestError("FORMAT_ATTACHMENT: 빈 파일은 등록할 수 없습니다.")
        total += size
    if total > MAX_FILE_BYTES:
        raise IngestError("FORMAT_ATTACHMENT: 첨부파일의 합계 용량이 서버 제한을 초과했습니다.")
    return names


def queue_message(client, guild, channel, message, inbox=INBOX, *, fields=None):
    author = message.get("author", {})
    attachments = message.get("attachments", [])
    if author.get("bot") or message.get("webhook_id"):
        return False
    content = message.get("content", "")
    # Ignore ordinary conversation; a file or explicit seminar marker is an upload attempt.
    heading = next((line.strip() for line in content.splitlines() if line.strip()), "") if isinstance(content, str) else ""
    if fields is None and not attachments and heading not in SEMINAR_HEADINGS:
        return False
    if fields is None:
        fields = parse_seminar_message(content)
    else:
        fields = validate_seminar_fields(fields.get("title"), fields.get("presented_on"), fields.get("summary"))
    names = validate_attachments(attachments)
    message_id = message["id"]
    base = f"discord-{channel}-{message_id}"
    manifest = inbox / (base + ".json")
    if manifest.exists() or (inbox / ".processed" / manifest.name).exists():
        return False
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
    payload = {
        "source": "discord",
        "source_message_id": f"discord:{guild}:{channel}:{message_id}",
        "presenter_discord": _clean_text(presenter, "presenter", 80),
        "uploaded_at": message["timestamp"],
        **fields,
        "files": files,
    }
    # Commit only after every file is complete. Existing website watcher ingests it.
    atomic_json(manifest, payload)
    return True


def collect_message(client, guild, channel, message, forms, inbox=INBOX):
    """Offer a form for attachments, while keeping complete text uploads working."""
    if message.get("author", {}).get("bot") or message.get("webhook_id"):
        return "ignored"
    if message.get("attachments"):
        try:
            parse_seminar_message(message.get("content", ""))
        except IngestError:
            return "prompted" if forms.offer(message) else "ignored"
    return "queued" if queue_message(client, guild, channel, message, inbox) else "ignored"


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
    print("Setup complete. Start 10-START-DISCORD-SYNC.bat, then attach a NEW seminar file and click the bot's form button.")


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
    from discord_sync.gateway import Gateway
    from discord_sync.interactions import InteractiveSeminars
    forms = InteractiveSeminars(Client(config["token"]), config["guild"], channel)
    gateway = Gateway(config["token"], forms.handle)
    gateway.start()
    LOG.info("Connecting Discord forms. Website must run separately; checking uploads every 15 seconds.")
    was_ready = False
    try:
        while True:
            if gateway.failed:
                raise RuntimeError(gateway.failed)
            if not gateway.ready.is_set():
                if was_ready:
                    LOG.warning("Discord forms disconnected; uploads will resume after reconnection.")
                was_ready = False
                time.sleep(2)
                continue
            if not was_ready:
                LOG.info("Collector ready for channel %s. Forms ready: upload a file, then click the bot's button.", channel)
                was_ready = True
            try:
                for message in new_messages(client, channel, cursor):
                    try:
                        result = collect_message(client, config["guild"], channel, message, forms)
                    except IngestError as exc:
                        # An invalid file must not block subsequent uploads.
                        atomic_json(STATE / ("rejected-" + message["id"] + ".json"), {"id": message["id"], "reason": str(exc)})
                        LOG.warning("Rejected message %s: %s See docs/discord-setup.md.", message["id"], exc)
                    else:
                        if result == "queued":
                            LOG.info("Queued message %s for website ingestion", message["id"])
                        elif result == "prompted":
                            LOG.info("Sent form prompt for message %s", message["id"])
                    cursor = message["id"]
                    atomic_json(checkpoint, {"cursor": cursor})
            except AttachmentError as exc:
                LOG.warning("Attachment download failed: HTTP %s, host=%s; checkpoint retained. "
                            "Retrying with freshly fetched message URLs in 15 seconds.", exc.status, exc.host)
            except ApiError as exc:
                if exc.status in (401, 403):
                    raise RuntimeError(f"Discord HTTP {exc.status}. Check the bot token and View Channel, Read Message History, Send Messages permissions.") from None
                LOG.warning("Discord request failed; retrying in 15 seconds (HTTP %s).", exc.status)
            except Exception as exc:
                # Never log token, signed URL, response content or user message.
                LOG.warning("Collection failed (%s); checkpoint retained, retrying in 15 seconds.", type(exc).__name__)
            time.sleep(15)
    finally:
        gateway.close()
        forms.close()
        instance_lock.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Collector stopped.")
    except Exception as exc:
        print("Collector stopped:", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        sys.exit(1)
