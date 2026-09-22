#!/usr/bin/env python3
"""Static lab site + authenticated seminar archive ingest service.

The public API is read-only. Hermes or a Teams adapter posts a normalized,
authenticated JSON payload to /api/ingest. A background watcher also accepts
the same payload as *.json manifests in SEMINAR_INBOX_DIR.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import struct
import threading
import time
import unicodedata
import zlib
from datetime import date, datetime, timezone
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = Path(os.environ.get("SITE_DIR", ROOT / "site")).resolve()
DATA_DIR = Path(os.environ.get("SEMINAR_DATA_DIR", ROOT / "seminar-data")).resolve()
INBOX_DIR = Path(os.environ.get("SEMINAR_INBOX_DIR", ROOT / "seminar-inbox")).resolve()
PRESENTER_MAP_PATH = Path(
    os.environ.get("PRESENTER_MAP_PATH", ROOT / "seminar_service" / "config" / "presenter-map.json")
).resolve()
UPLOAD_TOKEN = os.environ.get("SEMINAR_UPLOAD_TOKEN", "")
MAX_FILE_BYTES = int(os.environ.get("SEMINAR_MAX_FILE_MB", "100")) * 1024 * 1024
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
WATCH_INTERVAL = max(2, int(os.environ.get("SEMINAR_WATCH_INTERVAL", "5")))
ALLOWED_EXTENSIONS = {
    ext.strip().lower()
    for ext in os.environ.get(
        "SEMINAR_ALLOWED_EXTENSIONS",
        ".pdf,.ppt,.pptx,.doc,.docx,.xls,.xlsx,.zip,.txt,.md,.png,.jpg,.jpeg,.webp",
    ).split(",")
    if ext.strip()
}

ADMIN_AUTH_PATH = DATA_DIR / "admin-auth.json"
CONTENT_OVERRIDES_PATH = DATA_DIR / "site-content-overrides.json"
ADMIN_SESSION_SECONDS = 8 * 60 * 60
ADMIN_PASSWORD_ITERATIONS = 600_000
ADMIN_MAX_BODY_BYTES = 2 * 1024 * 1024
PEOPLE_PHOTO_MAX_BYTES = 2 * 1024 * 1024
PEOPLE_PHOTO_MAX_DIMENSION = 1200
ADMIN_PAGES = {
    "index.html",
    "research.html",
    "people.html",
    "publications.html",
    "projects.html",
    "news.html",
    "seminars.html",
    "resources.html",
    "contact.html",
}

INDEX_PATH = DATA_DIR / "index.json"
ITEMS_DIR = DATA_DIR / "items"
LOCK = threading.RLock()
ADMIN_LOCK = threading.RLock()
ADMIN_SESSIONS: dict[str, float] = {}
ADMIN_FAILURES: dict[str, list[float]] = {}
LOG = logging.getLogger("seminar-service")


class IngestError(ValueError):
    pass


class DeletedSeminarError(IngestError):
    pass


class PhotoTooLargeError(IngestError):
    pass


def _ensure_layout() -> None:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        _atomic_json(INDEX_PATH, [])
    if not CONTENT_OVERRIDES_PATH.exists():
        _atomic_json(CONTENT_OVERRIDES_PATH, {"version": 1, "global": {"ko": {}, "en": {}}, "pages": {}})
    _recover_deletions()


def configure_admin_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("관리자 비밀번호는 12자 이상이어야 합니다.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ADMIN_PASSWORD_ITERATIONS)
    with ADMIN_LOCK:
        _atomic_json(
            ADMIN_AUTH_PATH,
            {
                "algorithm": "pbkdf2_sha256",
                "iterations": ADMIN_PASSWORD_ITERATIONS,
                "salt": salt.hex(),
                "digest": digest.hex(),
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        ADMIN_SESSIONS.clear()


def _verify_admin_password(password: str) -> bool:
    try:
        record = _load_json(ADMIN_AUTH_PATH, {})
        iterations = int(record["iterations"])
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["digest"])
    except (KeyError, TypeError, ValueError):
        return False
    supplied = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(supplied, expected)


def _empty_content_overrides() -> dict[str, Any]:
    return {"version": 1, "global": {"ko": {}, "en": {}}, "pages": {}}


def _read_content_overrides() -> dict[str, Any]:
    value = _load_json(CONTENT_OVERRIDES_PATH, _empty_content_overrides())
    try:
        return _normalize_content_overrides(value)
    except ValueError:
        LOG.exception("invalid site content overrides; serving an empty set")
        return _empty_content_overrides()


def _normalize_content_overrides(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("콘텐츠 데이터는 객체여야 합니다.")
    normalized: dict[str, Any] = {"version": 1, "global": {"ko": {}, "en": {}}, "pages": {}}
    field_count = 0
    character_count = 0

    def clean_map(raw: Any) -> dict[str, str]:
        nonlocal field_count, character_count
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ValueError("편집 항목은 객체여야 합니다.")
        result: dict[str, str] = {}
        for key, text in raw.items():
            if not isinstance(key, str) or not key or len(key) > 500:
                raise ValueError("올바르지 않은 콘텐츠 키입니다.")
            if not isinstance(text, str) or len(text) > 20_000:
                raise ValueError("텍스트 항목은 20,000자 이하여야 합니다.")
            if key.endswith("@href") and text and not re.match(r"^(?:https?://|mailto:|tel:|[#/?]|[A-Za-z0-9_.-]+(?:[/?#]|$))", text):
                raise ValueError("허용되지 않는 링크 형식입니다.")
            result[key] = text
            field_count += 1
            character_count += len(text)
        return result

    global_raw = value.get("global", {})
    if not isinstance(global_raw, dict):
        raise ValueError("공통 콘텐츠 형식이 올바르지 않습니다.")
    for lang in ("ko", "en"):
        normalized["global"][lang] = clean_map(global_raw.get(lang, {}))

    pages_raw = value.get("pages", {})
    if not isinstance(pages_raw, dict):
        raise ValueError("페이지 콘텐츠 형식이 올바르지 않습니다.")
    for page, languages in pages_raw.items():
        if page not in ADMIN_PAGES or not isinstance(languages, dict):
            raise ValueError("허용되지 않는 페이지입니다.")
        normalized["pages"][page] = {lang: clean_map(languages.get(lang, {})) for lang in ("ko", "en")}

    if field_count > 12_000 or character_count > 1_500_000:
        raise ValueError("저장할 콘텐츠가 허용 범위를 넘었습니다.")
    return normalized


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise IngestError(f"JSON 형식이 올바르지 않습니다: {path.name}: {exc}") from exc


def _known_people_ids() -> set[str]:
    """The deployed roster owns identities; server overrides never create people."""
    source = (SITE_DIR / "js" / "data.js").read_text(encoding="utf-8")
    match = re.search(r"window\.SITE_DATA\s*=\s*(\{.*\})\s*;?\s*$", source, re.DOTALL)
    if match is None:
        raise IngestError("구성원 원본 데이터를 읽을 수 없습니다.")
    data = json.loads(match.group(1))
    people = [data.get("professor", {}), *data.get("members", []), *data.get("alumni", [])]
    return {person["id"] for person in people if isinstance(person, dict)
            and isinstance(person.get("id"), str)
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", person["id"])}


def _normalize_profile_links(value: Any) -> dict[str, str]:
    names = {"github", "linkedin", "website"}
    if not isinstance(value, dict) or not set(value).issubset(names):
        raise IngestError("GitHub, LinkedIn, 웹페이지 링크 형식을 확인해 주세요.")
    links = {}
    for name in ("github", "linkedin", "website"):
        raw = value.get(name, "")
        if not isinstance(raw, str) or len(raw) > 2048:
            raise IngestError("링크는 2,048자 이하의 문자열이어야 합니다.")
        # urlsplit strips some control characters, so reject them before parsing.
        if any(ord(char) < 32 or ord(char) == 127 for char in unquote(raw)):
            raise IngestError("링크에 제어 문자를 넣을 수 없습니다.")
        url = raw.strip()
        if not url:
            links[name] = ""
            continue
        if any(char.isspace() for char in url) or any(char in url for char in '\\<>"'):
            raise IngestError("올바른 웹 주소를 입력해 주세요.")
        try:
            parsed = urlsplit(url)
            hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
            if parsed.scheme not in {"http", "https"} or not hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("invalid URL")
            # Accessing port checks malformed and out-of-range values.
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("invalid port")
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                if len(hostname) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                                 for label in hostname.split(".")):
                    raise ValueError("invalid hostname")
        except (ValueError, UnicodeError) as exc:
            raise IngestError("로그인 정보가 없는 http 또는 https 주소를 입력해 주세요.") from exc
        if name == "github" and hostname not in {"github.com", "www.github.com"}:
            raise IngestError("GitHub 링크는 github.com 주소여야 합니다.")
        if name == "linkedin" and not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
            raise IngestError("LinkedIn 링크는 linkedin.com 주소여야 합니다.")
        links[name] = url
    return links


def _read_people_store() -> dict[str, Any]:
    value = _load_json(DATA_DIR / "people" / "profiles.json", {"version": 1, "profiles": {}})
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("profiles"), dict):
        raise IngestError("구성원 설정 파일 형식이 올바르지 않습니다.")
    result: dict[str, Any] = {"version": 1, "profiles": {}}
    for person_id, profile in value["profiles"].items():
        if not isinstance(profile, dict) or not isinstance(person_id, str):
            raise IngestError("구성원 설정 파일 형식이 올바르지 않습니다.")
        photo = profile.get("photo", "")
        if not isinstance(photo, str) or (photo and not re.fullmatch(r"/people-photos/[a-f0-9]{32}\.png", photo)):
            raise IngestError("구성원 사진 경로가 올바르지 않습니다.")
        result["profiles"][person_id] = {"links": _normalize_profile_links(profile.get("links", {})), "photo": photo}
    return result


def _public_people_profiles() -> dict[str, Any]:
    known_ids = _known_people_ids()
    store = _read_people_store()
    return {"version": 1, "profiles": {key: value for key, value in store["profiles"].items() if key in known_ids}}


def _png_chunk(kind: bytes, content: bytes) -> bytes:
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)


def _normalize_people_png(body: bytes) -> bytes:
    """Accept only bounded canvas PNGs and remove all non-pixel metadata."""
    if len(body) > PEOPLE_PHOTO_MAX_BYTES:
        raise PhotoTooLargeError("변환된 사진은 2MB 이하여야 합니다.")
    if not body.startswith(b"\x89PNG\r\n\x1a\n"):
        raise IngestError("PNG 이미지 형식이 올바르지 않습니다.")
    offset, header, compressed = 8, None, bytearray()
    data_started, data_finished, ended = False, False, False
    while offset < len(body):
        if offset + 12 > len(body):
            raise IngestError("PNG 이미지가 손상됐습니다.")
        size = struct.unpack(">I", body[offset:offset + 4])[0]
        kind = body[offset + 4:offset + 8]
        if size > len(body) - offset - 12 or not re.fullmatch(b"[A-Za-z]{4}", kind) or kind[2] & 0x20:
            raise IngestError("PNG 이미지가 손상됐습니다.")
        content = body[offset + 8:offset + 8 + size]
        checksum = struct.unpack(">I", body[offset + 8 + size:offset + 12 + size])[0]
        if checksum != zlib.crc32(kind + content) & 0xFFFFFFFF:
            raise IngestError("PNG 이미지 검사에 실패했습니다.")
        offset += size + 12
        if header is None and kind != b"IHDR":
            raise IngestError("PNG 헤더가 올바르지 않습니다.")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise IngestError("PNG 헤더가 올바르지 않습니다.")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", content)
            if not 1 <= width <= PEOPLE_PHOTO_MAX_DIMENSION or not 1 <= height <= PEOPLE_PHOTO_MAX_DIMENSION:
                raise IngestError("사진의 가로와 세로는 각각 1,200px 이하여야 합니다.")
            if depth != 8 or color not in {2, 6} or (compression, filtering, interlace) != (0, 0, 0):
                raise IngestError("관리자 화면에서 사진을 다시 선택해 PNG로 변환해 주세요.")
            header = content
        elif kind == b"IDAT":
            if data_finished:
                raise IngestError("PNG 데이터 순서가 올바르지 않습니다.")
            data_started = True
            compressed.extend(content)
        elif kind == b"IEND":
            if size != 0 or not data_started or offset != len(body):
                raise IngestError("PNG 이미지 끝부분이 올바르지 않습니다.")
            ended = True
            break
        else:
            if data_started:
                data_finished = True
            # Unknown critical chunks cannot be decoded safely; ancillary data is discarded.
            if not kind[0] & 0x20:
                raise IngestError("지원하지 않는 PNG 이미지 형식입니다.")
    if not ended or header is None:
        raise IngestError("PNG 이미지가 완전하지 않습니다.")
    stride = width * (4 if color == 6 else 3) + 1
    expected = stride * height
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("invalid pixel data length")
        if any(pixels[row * stride] > 4 for row in range(height)):
            raise ValueError("invalid row filter")
    except (ValueError, zlib.error) as exc:
        raise IngestError("PNG 픽셀 데이터가 올바르지 않습니다.") from exc
    normalized = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(pixels)) + _png_chunk(b"IEND", b"")
    if len(normalized) > PEOPLE_PHOTO_MAX_BYTES:
        raise PhotoTooLargeError("사진을 더 작은 크기로 선택해 주세요. 최대 크기는 2MB입니다.")
    return normalized


def _remove_people_photo(photo: str) -> None:
    if not photo:
        return
    try:
        (DATA_DIR / "people" / "photos" / photo.rsplit("/", 1)[-1]).unlink(missing_ok=True)
    except OSError:
        # Metadata is the publication authority, so failed cleanup never exposes an old photo.
        LOG.warning("unused people photo could not be removed; it is no longer public")


def _update_people_profile(person_id: str, *, links: dict[str, str] | None = None,
                           photo: bytes | None = None, clear_photo: bool = False) -> dict[str, Any] | None:
    with ADMIN_LOCK:
        if person_id not in _known_people_ids():
            return None
        store = _read_people_store()
        previous = store["profiles"].get(person_id, {"links": _normalize_profile_links({}), "photo": ""})
        profile = {"links": previous["links"].copy(), "photo": previous["photo"]}
        new_path = None
        if links is not None:
            profile["links"] = links
        if photo is not None:
            photos_dir = DATA_DIR / "people" / "photos"
            photos_dir.mkdir(parents=True, exist_ok=True)
            new_path = photos_dir / (secrets.token_hex(16) + ".png")
            temporary = new_path.with_suffix(".tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(photo)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(new_path)
            finally:
                temporary.unlink(missing_ok=True)
            profile["photo"] = "/people-photos/" + new_path.name
        elif clear_photo:
            profile["photo"] = ""
        store["profiles"][person_id] = profile
        try:
            _atomic_json(DATA_DIR / "people" / "profiles.json", store)
        except Exception:
            if new_path is not None:
                _remove_people_photo(profile["photo"])
            raise
        if profile["photo"] != previous["photo"]:
            _remove_people_photo(previous["photo"])
        return profile


def _clean_text(value: Any, field: str, max_length: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_length:
        raise IngestError(f"{field} 값이 너무 깁니다.")
    return text


def _safe_filename(value: Any) -> str:
    name = Path(unicodedata.normalize("NFKC", str(value or ""))).name.strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[<>:\"/\\|?*]", "_", name).strip(" .")
    if not name or name in {".", ".."}:
        raise IngestError("파일 이름이 비어 있습니다.")
    if len(name) > 180:
        stem, suffix = Path(name).stem[:140], Path(name).suffix[:20]
        name = stem + suffix
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise IngestError(f"허용하지 않는 파일 형식입니다: {suffix or '(확장자 없음)'}")
    return name


def _normalize_datetime(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestError("uploaded_at은 ISO 8601 날짜여야 합니다.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_presented_on(value: Any) -> str:
    if value in (None, ""):
        return ""
    raw = str(value).strip()
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
            raise ValueError
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise IngestError("presented_on은 YYYY-MM-DD 형식의 유효한 날짜여야 합니다.") from None


def _load_presenter_map() -> dict[str, dict[str, str]]:
    mapping = _load_json(PRESENTER_MAP_PATH, {})
    return {
        "by_teams_user_id": {str(k).lower(): str(v) for k, v in mapping.get("by_teams_user_id", {}).items()},
        "by_email": {str(k).lower(): str(v) for k, v in mapping.get("by_email", {}).items()},
    }


def _resolve_presenter(payload: dict[str, Any]) -> str:
    explicit = _clean_text(payload.get("presenter_discord"), "presenter_discord", 80)
    if explicit:
        return explicit
    mapping = _load_presenter_map()
    teams_id = str(payload.get("source_user_id") or "").strip().lower()
    email = str(payload.get("source_user_email") or "").strip().lower()
    presenter = mapping["by_teams_user_id"].get(teams_id) or mapping["by_email"].get(email)
    if not presenter:
        raise IngestError(
            "발표자의 디스코드 서버 닉네임을 찾지 못했습니다. presenter-map.json에 Teams 사용자 ID 또는 이메일을 등록하세요."
        )
    return _clean_text(presenter, "presenter", 80)


def _deletion_path(source_message_id: str) -> Path:
    digest = hashlib.sha256(source_message_id.encode("utf-8")).hexdigest()
    return DATA_DIR / "deleted" / f"{digest}.json"


def _read_index(include_deleted: bool = False) -> list[dict[str, Any]]:
    rows = _load_json(INDEX_PATH, [])
    if not isinstance(rows, list):
        raise IngestError("index.json은 배열이어야 합니다.")
    if include_deleted:
        return rows
    # A tombstone is the deletion commit. Hide it even if a process stopped
    # before index/trash cleanup, or Windows temporarily held an open PDF.
    return [row for row in rows if not _deletion_path(str(row.get("source_message_id", ""))).is_file()]


def _finalize_deletion(record: dict[str, Any]) -> None:
    item_id = record["id"]
    if not re.fullmatch(r"[0-9]{8}-[a-f0-9]{10}", item_id):
        raise IngestError("올바르지 않은 자료 ID입니다.")
    rows = [row for row in _read_index(include_deleted=True)
            if row.get("id") != item_id and row.get("source_message_id") != record["source_message_id"]]
    _atomic_json(INDEX_PATH, rows)
    item_dir = ITEMS_DIR / item_id
    if item_dir.exists():
        trash = DATA_DIR / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / item_id
        if destination.exists():
            # Never overwrite a previous recovery copy.
            destination = trash / f"{item_id}-{secrets.token_hex(4)}"
        item_dir.replace(destination)


def _recover_deletions() -> None:
    with LOCK:
        for path in (DATA_DIR / "deleted").glob("*.json"):
            try:
                record = _load_json(path, {})["record"]
                _finalize_deletion(record)
            except Exception:
                LOG.warning("Deleted seminar cleanup deferred: %s", path.name)


def delete_seminar(item_id: str) -> bool:
    if not re.fullmatch(r"[0-9]{8}-[a-f0-9]{10}", item_id):
        return False
    with LOCK:
        record = next((row for row in _read_index() if row.get("id") == item_id), None)
        if record is None:
            return False
        _atomic_json(_deletion_path(record["source_message_id"]), {
            "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "record": record,
        })
        try:
            _finalize_deletion(record)
        except Exception:
            # The durable marker already prevents reads and replay. Recover on
            # next startup rather than restoring a publicly deleted item.
            LOG.warning("Seminar %s hidden; private trash cleanup deferred until restart", item_id)
        return True


def _decode_files(payload: dict[str, Any], manifest_dir: Path | None = None) -> list[tuple[str, bytes]]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise IngestError("files 배열에 파일을 하나 이상 넣어야 합니다.")
    result: list[tuple[str, bytes]] = []
    total = 0
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise IngestError("files의 각 항목은 객체여야 합니다.")
        if manifest_dir is not None and raw.get("path"):
            source = (manifest_dir / str(raw["path"])).resolve()
            try:
                source.relative_to(INBOX_DIR)
            except ValueError as exc:
                raise IngestError("inbox 폴더 밖의 파일은 읽을 수 없습니다.") from exc
            if not source.is_file():
                raise IngestError(f"파일을 찾을 수 없습니다: {raw['path']}")
            name = _safe_filename(raw.get("name") or source.name)
            data = source.read_bytes()
        else:
            name = _safe_filename(raw.get("name"))
            encoded = raw.get("content_base64")
            if not isinstance(encoded, str):
                raise IngestError(f"{name}: content_base64가 필요합니다.")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise IngestError(f"{name}: Base64 데이터가 올바르지 않습니다.") from exc
        if not data:
            raise IngestError(f"빈 파일은 저장할 수 없습니다: {name}")
        total += len(data)
        if total > MAX_FILE_BYTES:
            raise IngestError(f"파일 합계가 {MAX_FILE_BYTES // 1024 // 1024}MB 제한을 넘었습니다.")
        result.append((name, data))
    return result


def ingest(payload: dict[str, Any], manifest_dir: Path | None = None) -> tuple[dict[str, Any], bool]:
    if not isinstance(payload, dict):
        raise IngestError("요청 본문은 JSON 객체여야 합니다.")
    source_message_id = _clean_text(payload.get("source_message_id"), "source_message_id", 200)
    if not source_message_id:
        raise IngestError("중복 업로드 방지를 위해 source_message_id가 필요합니다.")
    with LOCK:
        if _deletion_path(source_message_id).is_file():
            raise DeletedSeminarError("관리자가 삭제한 원본 메시지는 다시 등록하지 않습니다. 새 메시지로 업로드하세요.")
    title = _clean_text(payload.get("title"), "title", 180)
    summary = _clean_text(payload.get("summary"), "summary", 1000)
    presenter = _resolve_presenter(payload)
    uploaded_at = _normalize_datetime(payload.get("uploaded_at"))
    presented_on = _normalize_presented_on(payload.get("presented_on"))
    source = _clean_text(payload.get("source") or "hermes", "source", 40)
    files = _decode_files(payload, manifest_dir)

    with LOCK:
        if _deletion_path(source_message_id).is_file():
            raise DeletedSeminarError("관리자가 삭제한 원본 메시지는 다시 등록하지 않습니다. 새 메시지로 업로드하세요.")
        rows = _read_index()
        for existing in rows:
            if existing.get("source_message_id") == source_message_id:
                return existing, False

        digest = hashlib.sha256(source_message_id.encode("utf-8")).hexdigest()[:10]
        item_id = uploaded_at[:10].replace("-", "") + "-" + digest
        item_dir = ITEMS_DIR / item_id
        if item_dir.exists():
            raise IngestError("자료 ID 충돌이 발생했습니다. source_message_id를 확인하세요.")
        item_dir.mkdir(parents=True)
        saved_files: list[dict[str, Any]] = []
        try:
            used: set[str] = set()
            for name, content in files:
                candidate = name
                counter = 2
                while candidate.lower() in used:
                    p = Path(name)
                    candidate = f"{p.stem}-{counter}{p.suffix}"
                    counter += 1
                used.add(candidate.lower())
                path = item_dir / candidate
                path.write_bytes(content)
                saved_files.append(
                    {
                        "name": candidate,
                        "url": f"/seminar-files/{item_id}/{quote(candidate)}",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            record = {
                "id": item_id,
                "title": title or Path(saved_files[0]["name"]).stem,
                "presenter": presenter,
                "uploaded_at": uploaded_at,
                "presented_on": presented_on,
                "summary": summary,
                "source": source,
                "source_message_id": source_message_id,
                "files": saved_files,
            }
            (item_dir / "metadata.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            rows.append(record)
            rows.sort(key=lambda row: row.get("uploaded_at", ""), reverse=True)
            _atomic_json(INDEX_PATH, rows)
        except Exception:
            shutil.rmtree(item_dir, ignore_errors=True)
            raise
    return record, True


def _process_inbox_manifest(path: Path) -> None:
    payload = _load_json(path, {})
    try:
        record, created = ingest(payload, path.parent)
    except DeletedSeminarError:
        record = None
    processed = INBOX_DIR / ".processed"
    processed.mkdir(exist_ok=True)
    target = processed / path.name
    if target.exists():
        target = processed / f"{path.stem}-{int(time.time())}.json"
    path.replace(target)
    if record is None:
        LOG.info("inbox ignored previously deleted seminar: %s", path.name)
    else:
        LOG.info("inbox %s: %s (%s)", "saved" if created else "duplicate", record["title"], record["id"])


def _watch_inbox() -> None:
    while True:
        for path in sorted(INBOX_DIR.glob("*.json")):
            try:
                _process_inbox_manifest(path)
                error_path = path.with_suffix(path.suffix + ".error.txt")
                if error_path.exists():
                    error_path.unlink()
            except Exception as exc:  # keep source files for manual recovery
                error_path = path.with_suffix(path.suffix + ".error.txt")
                error_path.write_text(str(exc) + "\n", encoding="utf-8")
                LOG.warning("inbox rejected %s: %s", path.name, exc)
        time.sleep(WATCH_INTERVAL)


class Handler(SimpleHTTPRequestHandler):
    server_version = "AILabSeminar/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def _json(self, status: int, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self) -> bool:
        if not UPLOAD_TOKEN:
            return False
        supplied = self.headers.get("Authorization", "")
        if supplied.startswith("Bearer "):
            supplied = supplied[7:]
        else:
            supplied = self.headers.get("X-Seminar-Token", "")
        return hmac.compare_digest(supplied.encode(), UPLOAD_TOKEN.encode())

    def _read_json_body(self, limit: int = ADMIN_MAX_BODY_BYTES) -> Any:
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise IngestError("application/json 형식이 필요합니다.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > limit:
            raise IngestError("요청 크기가 허용 범위를 벗어났습니다.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        return forwarded or self.client_address[0]

    def _session_hash(self) -> str | None:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("ailab_admin")
            if token is None or not token.value:
                return None
            return hashlib.sha256(token.value.encode("ascii")).hexdigest()
        except (KeyError, UnicodeEncodeError):
            return None

    def _admin_authenticated(self) -> bool:
        session_hash = self._session_hash()
        if not session_hash:
            return False
        now = time.time()
        with ADMIN_LOCK:
            expired = [key for key, deadline in ADMIN_SESSIONS.items() if deadline <= now]
            for key in expired:
                ADMIN_SESSIONS.pop(key, None)
            deadline = ADMIN_SESSIONS.get(session_hash, 0)
            if deadline <= now:
                return False
            ADMIN_SESSIONS[session_hash] = now + ADMIN_SESSION_SECONDS
            return True

    def _require_admin(self) -> bool:
        if self._admin_authenticated():
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "admin_login_required"})
        return False

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        scheme = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip().lower()
        return (parsed.scheme in {"http", "https"} and parsed.scheme == scheme
                and parsed.netloc.lower() == self.headers.get("Host", "").lower())

    def _set_admin_cookie(self, token: str, max_age: int) -> None:
        cookie = SimpleCookie()
        cookie["ailab_admin"] = token
        cookie["ailab_admin"]["path"] = "/"
        cookie["ailab_admin"]["httponly"] = True
        cookie["ailab_admin"]["samesite"] = "Strict"
        cookie["ailab_admin"]["max-age"] = str(max_age)
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            cookie["ailab_admin"]["secure"] = True
        self.send_header("Set-Cookie", cookie["ailab_admin"].OutputString())

    def _login_limited(self, ip: str) -> bool:
        cutoff = time.time() - 600
        with ADMIN_LOCK:
            recent = [stamp for stamp in ADMIN_FAILURES.get(ip, []) if stamp >= cutoff]
            ADMIN_FAILURES[ip] = recent
            return len(recent) >= 5

    def _record_login_failure(self, ip: str) -> None:
        with ADMIN_LOCK:
            ADMIN_FAILURES.setdefault(ip, []).append(time.time())

    def _people_admin_request(self, path: str, operation: str) -> None:
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return
        if not self._require_admin():
            return
        pattern = r"/api/admin/people/([a-z0-9][a-z0-9-]{0,79})" + ("/photo" if operation != "links" else "")
        match = re.fullmatch(pattern, path)
        if match is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            person_id = match.group(1)
            if person_id not in _known_people_ids():
                self._json(HTTPStatus.NOT_FOUND, {"error": "person_not_found"})
                return
            if operation == "links":
                payload = self._read_json_body(16 * 1024)
                if not isinstance(payload, dict) or set(payload) != {"links"}:
                    raise IngestError("links 객체를 보내 주세요.")
                profile = _update_people_profile(person_id, links=_normalize_profile_links(payload["links"]))
            elif operation == "photo":
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "image/png":
                    raise IngestError("관리자 화면에서 선택한 PNG 사진을 업로드해 주세요.")
                length = int(self.headers.get("Content-Length", "0"))
                if length > PEOPLE_PHOTO_MAX_BYTES:
                    raise PhotoTooLargeError("변환된 사진은 2MB 이하여야 합니다.")
                if length <= 0 or self.headers.get("Transfer-Encoding"):
                    raise IngestError("사진 요청 크기가 올바르지 않습니다.")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise IngestError("사진 업로드가 완료되지 않았습니다.")
                profile = _update_people_profile(person_id, photo=_normalize_people_png(body))
            else:
                profile = _update_people_profile(person_id, clear_photo=True)
            if profile is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "person_not_found"})
                return
            self._json(HTTPStatus.OK, {"ok": True, "profile": profile})
        except PhotoTooLargeError as exc:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(exc)})
        except (IngestError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            LOG.exception("unexpected people profile update failure")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    def _people_photo(self, path: str, *, head_only: bool = False) -> None:
        if not re.fullmatch(r"/people-photos/[a-f0-9]{32}\.png", path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            with ADMIN_LOCK:
                profiles = _public_people_profiles()["profiles"]
                if not any(profile["photo"] == path for profile in profiles.values()):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                candidate = DATA_DIR / "people" / "photos" / path.rsplit("/", 1)[-1]
                if candidate.is_symlink() or not candidate.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                handle = candidate.open("rb")
            with handle:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not head_only:
                    shutil.copyfileobj(handle, self.wfile)
        except Exception:
            LOG.exception("unexpected people photo read failure")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_HEAD(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/people-photos/"):
            self._people_photo(path, head_only=True)
            return
        super().do_HEAD()

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path == "/api/people-profiles":
            try:
                with ADMIN_LOCK:
                    self._json(HTTPStatus.OK, _public_people_profiles())
            except Exception:
                LOG.exception("unexpected people profiles read failure")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})
            return
        if path.startswith("/people-photos/"):
            self._people_photo(path)
            return
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True, "items": len(_read_index()), "ingest_enabled": bool(UPLOAD_TOKEN)})
            return
        if path == "/api/seminars":
            with LOCK:
                self._json(HTTPStatus.OK, _read_index())
            return
        if path == "/api/content-overrides":
            with ADMIN_LOCK:
                self._json(HTTPStatus.OK, _read_content_overrides())
            return
        if path == "/api/admin/status":
            self._json(
                HTTPStatus.OK,
                {"configured": ADMIN_AUTH_PATH.is_file(), "authenticated": self._admin_authenticated()},
            )
            return
        if path == "/api/admin/content":
            if not self._require_admin():
                return
            with ADMIN_LOCK:
                self._json(HTTPStatus.OK, _read_content_overrides())
            return
        if path.startswith("/seminar-files/"):
            relative = path.removeprefix("/seminar-files/")
            candidate = (ITEMS_DIR / relative).resolve()
            try:
                candidate.relative_to(ITEMS_DIR)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            with LOCK:
                parts = Path(relative).parts
                record = next((row for row in _read_index() if len(parts) == 2 and row.get("id") == parts[0]), None)
                if (record is None or not any(f.get("name") == candidate.name for f in record.get("files", []))
                        or not candidate.is_file() or candidate.name == "metadata.json"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                handle = candidate.open("rb")
                size = os.fstat(handle.fileno()).st_size
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            with handle:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if content_type not in {"application/pdf"} and not content_type.startswith("image/"):
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(candidate.name)}")
                self.end_headers()
                shutil.copyfileobj(handle, self.wfile)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/admin/people/"):
            self._people_admin_request(path, "photo")
            return
        if path == "/api/admin/login":
            if not self._origin_allowed():
                self._json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return
            if not ADMIN_AUTH_PATH.is_file():
                self._json(HTTPStatus.CONFLICT, {"error": "admin_not_configured"})
                return
            ip = self._client_ip()
            if self._login_limited(ip):
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "too_many_attempts"})
                return
            try:
                payload = self._read_json_body(16 * 1024)
                password = payload.get("password", "") if isinstance(payload, dict) else ""
                if not isinstance(password, str) or not _verify_admin_password(password):
                    self._record_login_failure(ip)
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
                    return
                token = secrets.token_urlsafe(32)
                session_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
                with ADMIN_LOCK:
                    ADMIN_FAILURES.pop(ip, None)
                    ADMIN_SESSIONS[session_hash] = time.time() + ADMIN_SESSION_SECONDS
                encoded = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self._set_admin_cookie(token, ADMIN_SESSION_SECONDS)
                self.end_headers()
                self.wfile.write(encoded)
            except (IngestError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path == "/api/admin/logout":
            if not self._origin_allowed():
                self._json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return
            session_hash = self._session_hash()
            if session_hash:
                with ADMIN_LOCK:
                    ADMIN_SESSIONS.pop(session_hash, None)
            encoded = b'{"ok":true}'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self._set_admin_cookie("", 0)
            self.end_headers()
            self.wfile.write(encoded)
            return
        if path != "/api/ingest":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            payload = self._read_json_body(MAX_FILE_BYTES * 2)
            record, created = ingest(payload)
            self._json(HTTPStatus.CREATED if created else HTTPStatus.OK, {"created": created, "item": record})
        except (IngestError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception:
            LOG.exception("unexpected ingest failure")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    def do_PUT(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/admin/people/"):
            self._people_admin_request(path, "links")
            return
        if path != "/api/admin/content":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return
        if not self._require_admin():
            return
        try:
            payload = self._read_json_body()
            normalized = _normalize_content_overrides(payload)
            with ADMIN_LOCK:
                _atomic_json(CONTENT_OVERRIDES_PATH, normalized)
            self._json(HTTPStatus.OK, {"ok": True})
        except (IngestError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception:
            LOG.exception("unexpected admin content failure")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/admin/people/"):
            self._people_admin_request(path, "clear_photo")
            return
        if not path.startswith("/api/admin/seminars/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
            return
        if not self._require_admin():
            return
        try:
            deleted = delete_seminar(path.removeprefix("/api/admin/seminars/"))
            if not deleted:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(HTTPStatus.OK, {"ok": True})
        except Exception:
            LOG.exception("unexpected seminar deletion failure")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    _ensure_layout()
    threading.Thread(target=_watch_inbox, name="seminar-inbox", daemon=True).start()
    if not UPLOAD_TOKEN:
        LOG.warning("SEMINAR_UPLOAD_TOKEN is empty: public reading works, HTTP ingest is disabled")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    LOG.info("serving %s on %s:%s; seminar data=%s", SITE_DIR, HOST, PORT, DATA_DIR)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
