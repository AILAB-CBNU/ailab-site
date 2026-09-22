#!/usr/bin/env python3
"""Poll one Teams channel and queue new file posts for the seminar archive.

This worker uses Microsoft Graph application credentials. It never exposes an
inbound webhook: the server PC makes outbound HTTPS requests to Microsoft and
writes completed manifests into the shared seminar inbox.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
ROOT = Path(__file__).resolve().parents[1]
TENANT_ID = os.environ.get("TEAMS_TENANT_ID", "").strip()
CLIENT_ID = os.environ.get("TEAMS_CLIENT_ID", "").strip()
TEAM_ID = os.environ.get("TEAMS_TEAM_ID", "").strip()
CHANNEL_ID = os.environ.get("TEAMS_CHANNEL_ID", "").strip()
INBOX_DIR = Path(os.environ.get("SEMINAR_INBOX_DIR", ROOT / "seminar-inbox")).resolve()
STATE_DIR = Path(os.environ.get("TEAMS_SYNC_STATE_DIR", ROOT / "teams-sync-state")).resolve()
STATE_PATH = STATE_DIR / "state.json"
DELEGATED_TOKEN_PATH = STATE_DIR / "delegated-token.json"
DELEGATED_SCOPES = os.environ.get(
    "TEAMS_DELEGATED_SCOPES", "offline_access Files.Read.All User.Read"
).strip()
POLL_SECONDS = max(15, int(os.environ.get("TEAMS_POLL_SECONDS", "60")))
MAX_PAGES = max(1, int(os.environ.get("TEAMS_MAX_PAGES", "10")))
MAX_FILE_BYTES = int(os.environ.get("SEMINAR_MAX_FILE_MB", "100")) * 1024 * 1024
IMPORT_EXISTING = os.environ.get("TEAMS_IMPORT_EXISTING", "false").lower() in {"1", "true", "yes"}
REQUIRED_TAG = unicodedata.normalize("NFKC", os.environ.get("TEAMS_REQUIRED_TAG", "")).strip()
ALLOWED_EXTENSIONS = {
    ext.strip().lower()
    for ext in os.environ.get(
        "SEMINAR_ALLOWED_EXTENSIONS",
        ".pdf,.ppt,.pptx,.doc,.docx,.xls,.xlsx,.zip,.txt,.md,.png,.jpg,.jpeg,.webp",
    ).split(",")
    if ext.strip()
}
LOG = logging.getLogger("teams-sync")


class SyncError(RuntimeError):
    pass


def _client_secret() -> str:
    direct = os.environ.get("TEAMS_CLIENT_SECRET", "").strip()
    secret_file = os.environ.get("TEAMS_CLIENT_SECRET_FILE", "").strip()
    if direct:
        return direct
    if secret_file:
        return Path(secret_file).read_text(encoding="utf-8").strip()
    return ""


def _required_config() -> None:
    missing = [
        name
        for name, value in {
            "TEAMS_TENANT_ID": TENANT_ID,
            "TEAMS_CLIENT_ID": CLIENT_ID,
            "TEAMS_CLIENT_SECRET (or TEAMS_CLIENT_SECRET_FILE)": _client_secret(),
            "TEAMS_TEAM_ID": TEAM_ID,
            "TEAMS_CHANNEL_ID": CHANNEL_ID,
        }.items()
        if not value
    ]
    if missing:
        raise SyncError("필수 Teams 설정이 없습니다: " + ", ".join(missing))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"initialized": False, "processed": []}
    except json.JSONDecodeError as exc:
        raise SyncError(f"동기화 상태 파일이 손상되었습니다: {exc}") from exc
    return {
        "initialized": bool(value.get("initialized")),
        "processed": [str(item) for item in value.get("processed", [])][-5000:],
    }


class GraphClient:
    def __init__(self) -> None:
        self.application_token = ""
        self.application_token_expires_at = 0.0

    def _application_access_token(self) -> str:
        if self.application_token and time.time() < self.application_token_expires_at - 120:
            return self.application_token
        body = urllib.parse.urlencode(
            {
                "client_id": CLIENT_ID,
                "client_secret": _client_secret(),
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }
        ).encode("ascii")
        request = urllib.request.Request(
            f"https://login.microsoftonline.com/{urllib.parse.quote(TENANT_ID, safe='')}/oauth2/v2.0/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        response = self._open(request)
        value = json.loads(response.decode("utf-8"))
        self.application_token = str(value["access_token"])
        self.application_token_expires_at = time.time() + int(value.get("expires_in", 3600))
        return self.application_token

    def _delegated_access_token(self) -> str:
        try:
            cached = json.loads(DELEGATED_TOKEN_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SyncError(
                "Teams 파일 로그인 정보가 없습니다. 서버에서 ./server/login-teams-files.sh를 한 번 실행하세요."
            ) from exc
        except (json.JSONDecodeError, OSError) as exc:
            raise SyncError(f"Teams 파일 로그인 정보가 손상되었습니다: {exc}") from exc

        if cached.get("access_token") and time.time() < float(cached.get("expires_at") or 0) - 120:
            return str(cached["access_token"])
        refresh_token = str(cached.get("refresh_token") or "")
        if not refresh_token:
            raise SyncError("Teams 파일 로그인 갱신 정보가 없습니다. ./server/login-teams-files.sh를 다시 실행하세요.")

        body = urllib.parse.urlencode(
            {
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
                "scope": DELEGATED_SCOPES,
                "grant_type": "refresh_token",
            }
        ).encode("ascii")
        request = urllib.request.Request(
            f"https://login.microsoftonline.com/{urllib.parse.quote(TENANT_ID, safe='')}/oauth2/v2.0/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        value = json.loads(self._open(request).decode("utf-8"))
        value["refresh_token"] = value.get("refresh_token") or refresh_token
        value["expires_at"] = time.time() + int(value.get("expires_in", 3600))
        _atomic_json(DELEGATED_TOKEN_PATH, value)
        DELEGATED_TOKEN_PATH.chmod(0o600)
        return str(value["access_token"])

    def _open(self, request: urllib.request.Request, limit: int | None = None) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if limit is None:
                    return response.read()
                declared = int(response.headers.get("Content-Length", "0") or 0)
                if declared and declared > limit:
                    raise SyncError(f"파일이 {limit // 1024 // 1024}MB 제한을 넘었습니다.")
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise SyncError(f"파일이 {limit // 1024 // 1024}MB 제한을 넘었습니다.")
                return data
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise SyncError(f"Microsoft Graph HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SyncError(f"Microsoft Graph 연결 실패: {exc.reason}") from exc

    def json(self, endpoint: str, *, delegated: bool = False) -> dict[str, Any]:
        url = endpoint if endpoint.startswith("https://") else GRAPH_ROOT + endpoint
        token = self._delegated_access_token() if delegated else self._application_access_token()
        request = urllib.request.Request(
            url,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        return json.loads(self._open(request).decode("utf-8"))

    def download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
        return self._open(request, MAX_FILE_BYTES)


def _html_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<attachment\b[^>]*>.*?</attachment>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _safe_filename(value: Any) -> str:
    name = Path(unicodedata.normalize("NFKC", str(value or ""))).name.strip()
    name = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "_", name).strip(" .")
    if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise SyncError(f"허용하지 않는 파일입니다: {name or '(이름 없음)'}")
    if len(name) > 180:
        name = Path(name).stem[:140] + Path(name).suffix[:20]
    return name


def _canonical_url(value: Any) -> str:
    parts = urllib.parse.urlsplit(str(value or ""))
    path = urllib.parse.unquote(parts.path).rstrip("/").lower()
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def _messages(client: GraphClient) -> list[dict[str, Any]]:
    team = urllib.parse.quote(TEAM_ID, safe="")
    channel = urllib.parse.quote(CHANNEL_ID, safe="")
    next_url = f"/teams/{team}/channels/{channel}/messages?$top=50"
    result: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        page = client.json(next_url)
        result.extend(item for item in page.get("value", []) if isinstance(item, dict))
        next_url = str(page.get("@odata.nextLink") or "")
        if not next_url:
            break
    return result


def _channel_folder(client: GraphClient) -> dict[str, Any]:
    team = urllib.parse.quote(TEAM_ID, safe="")
    channel = urllib.parse.quote(CHANNEL_ID, safe="")
    folder = client.json(f"/teams/{team}/channels/{channel}/filesFolder", delegated=True)
    if not folder.get("id") or not (folder.get("parentReference") or {}).get("driveId"):
        raise SyncError("Teams 채널의 SharePoint 폴더 정보를 읽지 못했습니다.")
    return folder


def _drive_item(client: GraphClient, folder: dict[str, Any], attachment: dict[str, Any]) -> dict[str, Any]:
    drive_id = str(folder["parentReference"]["driveId"])
    folder_id = str(folder["id"])
    content_url = str(attachment.get("contentUrl") or "")
    name = _safe_filename(attachment.get("name"))
    folder_url = _canonical_url(folder.get("webUrl"))
    attachment_url = _canonical_url(content_url)
    select = urllib.parse.quote(
        "id,name,size,webUrl,file,parentReference,@microsoft.graph.downloadUrl", safe=",@"
    )

    if folder_url and attachment_url.startswith(folder_url + "/"):
        relative = urllib.parse.unquote(urllib.parse.urlsplit(content_url).path)[
            len(urllib.parse.unquote(urllib.parse.urlsplit(str(folder.get("webUrl"))).path).rstrip("/")) :
        ].lstrip("/")
        encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in relative.split("/"))
        try:
            return client.json(
                f"/drives/{urllib.parse.quote(drive_id, safe='')}/items/{urllib.parse.quote(folder_id, safe='')}:/{encoded_path}"
                f"?$select={select}",
                delegated=True,
            )
        except SyncError:
            LOG.info("direct SharePoint path lookup failed for %s; trying drive search", name)

    query_name = name.replace("'", "''")
    endpoint = (
        f"/drives/{urllib.parse.quote(drive_id, safe='')}/root/search(q='{urllib.parse.quote(query_name, safe='')}')"
        f"?$select={select}&$top=50"
    )
    matches: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        page = client.json(endpoint, delegated=True)
        matches.extend(item for item in page.get("value", []) if item.get("name") == name and item.get("file"))
        endpoint = str(page.get("@odata.nextLink") or "")
        if not endpoint:
            break
    exact = [item for item in matches if _canonical_url(item.get("webUrl")) == attachment_url]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    raise SyncError(f"SharePoint에서 첨부 파일을 하나로 식별하지 못했습니다: {name}")


def _download_url(client: GraphClient, item: dict[str, Any]) -> str:
    url = str(item.get("@microsoft.graph.downloadUrl") or "")
    if url:
        return url
    drive_id = str((item.get("parentReference") or {}).get("driveId") or "")
    item_id = str(item.get("id") or "")
    if not drive_id or not item_id:
        raise SyncError("SharePoint 다운로드 식별자가 없습니다.")
    select = urllib.parse.quote("id,name,size,@microsoft.graph.downloadUrl", safe=",@")
    full = client.json(
        f"/drives/{urllib.parse.quote(drive_id, safe='')}/items/{urllib.parse.quote(item_id, safe='')}?$select={select}",
        delegated=True,
    )
    url = str(full.get("@microsoft.graph.downloadUrl") or "")
    if not url:
        raise SyncError("SharePoint가 임시 다운로드 URL을 반환하지 않았습니다.")
    return url


def _eligible_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict) or attachment.get("contentType") != "reference":
            continue
        try:
            _safe_filename(attachment.get("name"))
        except SyncError:
            continue
        if attachment.get("contentUrl"):
            result.append(attachment)
    return result


def _queue_message(client: GraphClient, folder: dict[str, Any], message: dict[str, Any]) -> bool:
    attachments = _eligible_attachments(message)
    text = _html_text((message.get("body") or {}).get("content"))
    if not attachments or (REQUIRED_TAG and REQUIRED_TAG.lower() not in text.lower()):
        return False
    user = ((message.get("from") or {}).get("user") or {})
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise SyncError("업로드한 Teams 사용자의 Entra ID를 찾지 못했습니다.")
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        raise SyncError("Teams 메시지 ID가 없습니다.")

    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:16]
    folder_name = "teams-" + digest
    download_dir = INBOX_DIR / folder_name
    download_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, str]] = []
    used: set[str] = set()
    total = 0
    for attachment in attachments:
        name = _safe_filename(attachment.get("name"))
        candidate = name
        counter = 2
        while candidate.lower() in used:
            candidate = f"{Path(name).stem}-{counter}{Path(name).suffix}"
            counter += 1
        used.add(candidate.lower())
        item = _drive_item(client, folder, attachment)
        declared = int(item.get("size") or 0)
        if declared and total + declared > MAX_FILE_BYTES:
            raise SyncError(f"첨부 파일 합계가 {MAX_FILE_BYTES // 1024 // 1024}MB 제한을 넘었습니다.")
        content = client.download(_download_url(client, item))
        total += len(content)
        if total > MAX_FILE_BYTES:
            raise SyncError(f"첨부 파일 합계가 {MAX_FILE_BYTES // 1024 // 1024}MB 제한을 넘었습니다.")
        temporary = download_dir / (candidate + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(download_dir / candidate)
        files.append({"path": f"{folder_name}/{candidate}", "name": candidate})

    subject = _html_text(message.get("subject"))
    title = subject or (text.splitlines()[0][:180] if text else Path(files[0]["name"]).stem)
    payload = {
        "source": "microsoft-teams-graph",
        "source_message_id": f"teams:{TEAM_ID}:{CHANNEL_ID}:{message_id}",
        "source_user_id": user_id,
        "source_user_email": "",
        "title": title,
        "summary": text[:1000],
        "uploaded_at": message.get("createdDateTime"),
        "files": files,
    }
    _atomic_json(INBOX_DIR / f"teams-{digest}.json", payload)
    LOG.info("queued Teams seminar: %s (%s file(s))", title, len(files))
    return True


def poll_once(client: GraphClient) -> None:
    messages = _messages(client)
    state = _load_state()
    processed_order = list(state["processed"])
    processed = set(processed_order)
    ids = [str(message.get("id") or "") for message in messages if message.get("id")]
    if not state["initialized"] and not IMPORT_EXISTING:
        _atomic_json(STATE_PATH, {"initialized": True, "processed": ids[-5000:]})
        LOG.info("initialized at current channel position (%s existing message(s) skipped)", len(ids))
        return

    folder: dict[str, Any] | None = None
    for message in reversed(messages):
        message_id = str(message.get("id") or "")
        if not message_id or message_id in processed:
            continue
        if _eligible_attachments(message):
            folder = folder or _channel_folder(client)
            _queue_message(client, folder, message)
        processed.add(message_id)
        processed_order.append(message_id)
        processed_order = processed_order[-5000:]
        _atomic_json(STATE_PATH, {"initialized": True, "processed": processed_order})


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    _required_config()
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    client = GraphClient()
    LOG.info("watching Teams channel %s every %ss", CHANNEL_ID, POLL_SECONDS)
    while True:
        try:
            poll_once(client)
        except Exception as exc:
            LOG.exception("Teams sync failed: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
