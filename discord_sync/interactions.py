"""Persistent, author-only Discord forms for seminar attachments.

Only IDs and bounded form drafts are saved locally. Interaction tokens stay in
the bounded worker queue; attachment URLs are fetched afresh after submission.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import queue
import re
import threading
from typing import Any

from discord_sync import app


LOG = logging.getLogger("discord-seminar-forms")
_NO_MENTIONS = {"parse": [], "replied_user": False}
_FIELD_LIMITS = {"title": 180, "presented_on": 10, "summary": 1000}
_WEBSITE = "https://ailab.cbnu.ac.kr/seminars.html"


def _snowflake(value: Any) -> str:
    text = str(value or "")
    return text if re.fullmatch(r"[0-9]{1,22}", text) else ""


def _safe_log(action: str, exc: Exception) -> None:
    # Exceptions from HTTP libraries can contain interaction tokens or signed URLs.
    status = getattr(exc, "status", None)
    LOG.warning("%s failed (%s, status=%s)", action, type(exc).__name__, status if isinstance(status, int) else "unknown")


def _button(message_id: str, *, retry: bool = False) -> list[dict[str, Any]]:
    return [{"type": 1, "components": [{"type": 2, "style": 1,
              "label": "다시 입력" if retry else "세미나 정보 입력",
              "custom_id": f"seminar:{'retry' if retry else 'open'}:{message_id}"}]}]


def _bounded_draft(fields: dict[str, Any]) -> dict[str, str]:
    return {key: value[:_FIELD_LIMITS[key]] for key, value in fields.items()
            if key in _FIELD_LIMITS and isinstance(value, str)}


def _markdown_escape(value: str) -> str:
    # Disable mention syntax as well as formatting; allowed_mentions is also empty.
    return re.sub(r"([\\`*_~|>#\[\]()!+\-])", r"\\\1", value).replace("@", "@\u200b")


class InteractiveSeminars:
    def __init__(self, client, guild, channel, state_dir=app.STATE, inbox=app.INBOX):
        self.client = client
        self.guild, self.channel = _snowflake(guild), _snowflake(channel)
        if not self.guild or not self.channel:
            raise ValueError("Invalid seminar guild or channel ID")
        self.forms = Path(state_dir) / "forms"
        self.inbox = Path(inbox)
        self._lock = threading.RLock()
        self._offering: set[str] = set()
        self._inflight: set[str] = set()
        self._jobs: queue.Queue = queue.Queue(maxsize=8)
        self._slots = threading.BoundedSemaphore(8)
        self._closed = threading.Event()
        self._worker = threading.Thread(target=self._work, name="discord-seminar-forms", daemon=True)
        self._worker.start()

    def _read(self, message_id: str) -> dict[str, Any] | None:
        try:
            record = json.loads((self.forms / (message_id + ".json")).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("message_id") != message_id or record.get("guild_id") != self.guild
                or record.get("channel_id") != self.channel or not _snowflake(record.get("author_id"))
                or record.get("status") not in {"pending", "queued", "rejected"}
                or not isinstance(record.get("draft"), dict)):
            raise ValueError("Invalid seminar form state")
        if record.get("prompt_id") and not _snowflake(record["prompt_id"]):
            raise ValueError("Invalid seminar prompt ID")
        return record

    def _save(self, record: dict[str, Any]) -> None:
        # Explicit schema keeps Discord payloads, URLs and tokens out of persistence.
        clean = {key: record[key] for key in ("version", "message_id", "author_id", "guild_id", "channel_id",
                                              "prompt_id", "status")}
        clean["draft"] = _bounded_draft(record.get("draft", {}))
        app.atomic_json(self.forms / (record["message_id"] + ".json"), clean)

    def offer(self, message) -> bool:
        if self._closed.is_set() or not isinstance(message, dict):
            return False
        author = message.get("author", {})
        attachments = message.get("attachments", [])
        if not isinstance(author, dict) or author.get("bot") or message.get("webhook_id") or not attachments:
            return False
        message_id, author_id = _snowflake(message.get("id")), _snowflake(author.get("id"))
        if not message_id or not author_id:
            raise app.IngestError("Invalid seminar author or message ID")
        if message.get("channel_id", self.channel) != self.channel or message.get("guild_id", self.guild) != self.guild:
            return False
        try:
            app.validate_attachments(attachments)
            rejected = False
        except app.IngestError:
            rejected = True
        with self._lock:
            record = self._read(message_id)
            if record is not None and record["author_id"] != author_id:
                raise app.IngestError("Seminar author does not match saved form")
            if record is not None and (record.get("prompt_id") or record["status"] == "queued"):
                return True
            if message_id in self._offering:
                return True
            if record is None:
                record = {"version": 1, "message_id": message_id, "author_id": author_id,
                          "guild_id": self.guild, "channel_id": self.channel, "prompt_id": "",
                          "status": "rejected" if rejected else "pending", "draft": {}}
                self._save(record)
            self._offering.add(message_id)
        try:
            if record["status"] == "rejected":
                size_mb = app.MAX_FILE_BYTES // (1024 * 1024)
                content = (f"이 자료는 등록할 수 없습니다. PDF·PPT·PPTX 등 지원 형식의 파일을 "
                           f"최대 10개, 총 {size_mb}MiB 이하로 새 메시지에 다시 올려 주세요.")
                components = []
            else:
                content = "첨부한 자료를 공개 홈페이지의 세미나 자료실에 등록하려면 아래 버튼으로 제목·발표일·요약을 입력해 주세요. 입력 후 제출하면 자료가 공개됩니다."
                components = _button(message_id)
            reply = self.client.post(f"/channels/{self.channel}/messages", {
                "content": content, "components": components, "allowed_mentions": dict(_NO_MENTIONS),
                "message_reference": {"message_id": message_id, "fail_if_not_exists": True},
                "nonce": "s" + message_id, "enforce_nonce": True,
            })
            prompt_id = _snowflake(reply.get("id") if isinstance(reply, dict) else None)
            if not prompt_id:
                raise RuntimeError("Discord did not return a prompt ID")
            with self._lock:
                record = self._read(message_id)
                record["prompt_id"] = prompt_id
                self._save(record)
            return True
        finally:
            with self._lock:
                self._offering.discard(message_id)

    def _callback(self, interaction, payload) -> bool:
        interaction_id = _snowflake(interaction.get("id"))
        token = interaction.get("token", "")
        if not interaction_id or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,512}", token):
            return False
        try:
            self.client.post(f"/interactions/{interaction_id}/{token}/callback", payload,
                             authenticated=False, timeout=2.5, retries=1)
            return True
        except Exception as exc:
            _safe_log("interaction acknowledgment", exc)
            return False

    def _private(self, interaction, message: str) -> None:
        self._callback(interaction, {"type": 4, "data": {"content": message, "flags": 64,
                                                       "allowed_mentions": dict(_NO_MENTIONS)}})

    def _modal(self, message_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        fields = [("title", "제목", 1, "발표 주제 또는 논문 제목", 1),
                  ("presented_on", "발표일", 1, "YYYY-MM-DD", 10),
                  ("summary", "요약", 2, "주요 내용과 공유하고 싶은 내용을 적어 주세요.", 1)]
        components = []
        for key, label, style, placeholder, minimum in fields:
            component = {"type": 4, "custom_id": key, "style": style, "required": True,
                         "min_length": minimum, "max_length": _FIELD_LIMITS[key], "placeholder": placeholder}
            value = _bounded_draft(draft).get(key, "")
            if value:
                component["value"] = value
            components.append({"type": 18, "label": label, "component": component})
        return {"type": 9, "data": {"custom_id": "seminar:submit:" + message_id,
                                    "title": "세미나 정보 입력", "components": components}}

    def handle(self, interaction) -> None:
        if self._closed.is_set() or not isinstance(interaction, dict):
            return
        reserved_id = ""
        acknowledged = False
        try:
            data = interaction.get("data", {})
            match = re.fullmatch(r"seminar:(open|retry|submit):([0-9]{1,22})", data.get("custom_id", "")) if isinstance(data, dict) else None
            if (match is None or interaction.get("guild_id") != self.guild
                    or interaction.get("channel_id") != self.channel):
                self._private(interaction, "지정된 세미나 채널의 자료 등록 버튼을 이용해 주세요.")
                return
            action, message_id = match.groups()
            if interaction.get("type") != (5 if action == "submit" else 3):
                self._private(interaction, "올바른 세미나 입력 요청이 아닙니다. 등록 버튼을 다시 눌러 주세요.")
                return
            member = interaction.get("member", {})
            user = member.get("user", {}) if isinstance(member, dict) else {}
            with self._lock:
                record = self._read(message_id)
                if record is None or record["author_id"] != _snowflake(user.get("id")):
                    response = "자료를 올린 본인만 세미나 정보를 입력할 수 있습니다."
                elif action == "open" and record.get("prompt_id") != _snowflake(interaction.get("message", {}).get("id")):
                    response = "이 자료의 원래 등록 버튼을 이용해 주세요."
                elif record["status"] == "queued":
                    response = "이미 등록 요청이 완료된 자료입니다. 세미나 자료실에서 확인해 주세요."
                elif record["status"] != "pending":
                    response = "지원 형식의 파일을 새 메시지에 올린 뒤 다시 등록해 주세요."
                elif message_id in self._inflight:
                    response = "이 자료를 처리하고 있습니다. 잠시 기다려 주세요."
                else:
                    response = ""
                draft = record.get("draft", {}).copy() if record else {}
            if response:
                self._private(interaction, response)
                return
            if action in {"open", "retry"}:
                self._callback(interaction, self._modal(message_id, draft))
                return
            if not _snowflake(interaction.get("application_id")):
                self._private(interaction, "입력 요청을 확인할 수 없습니다. 등록 버튼을 다시 눌러 주세요.")
                return
            with self._lock:
                if message_id in self._inflight:
                    response = "이 자료를 처리하고 있습니다. 잠시 기다려 주세요."
                elif not self._slots.acquire(blocking=False):
                    response = "등록 요청이 많습니다. 잠시 뒤 등록 버튼을 다시 눌러 주세요."
                else:
                    self._inflight.add(message_id)
                    reserved_id = message_id
                    response = ""
            if response:
                self._private(interaction, response)
                return
            # Acknowledge before any original-message fetch or file download.
            if not self._callback(interaction, {"type": 5, "data": {"flags": 64}}):
                return
            acknowledged = True
            if self._closed.is_set():
                return
            self._jobs.put_nowait({"message_id": message_id, "interaction": interaction})
            reserved_id = ""  # The worker now owns this reservation.
        except Exception as exc:
            _safe_log("interaction handling", exc)
            if not acknowledged:
                self._private(interaction, "입력 요청을 처리하지 못했습니다. 잠시 뒤 등록 버튼을 다시 눌러 주세요.")
        finally:
            if reserved_id:
                self._release(reserved_id)

    @staticmethod
    def _fields(components) -> dict[str, str]:
        values: dict[str, str] = {}
        remaining = 16

        def visit(component, depth=0):
            nonlocal remaining
            remaining -= 1
            if remaining < 0 or depth > 3 or not isinstance(component, dict):
                raise app.IngestError("Invalid seminar modal fields")
            if component.get("type") == 4:
                key, value = component.get("custom_id"), component.get("value")
                if key not in _FIELD_LIMITS or key in values or not isinstance(value, str):
                    raise app.IngestError("Invalid seminar modal fields")
                values[key] = value
            elif component.get("type") == 18:
                visit(component.get("component"), depth + 1)
            elif component.get("type") == 1 and isinstance(component.get("components"), list):
                for child in component["components"]:
                    visit(child, depth + 1)
            else:
                raise app.IngestError("Invalid seminar modal fields")

        if not isinstance(components, list):
            raise app.IngestError("Invalid seminar modal fields")
        for component in components:
            visit(component)
        if set(values) != set(_FIELD_LIMITS):
            raise app.IngestError("Invalid seminar modal fields")
        return values

    def _edit_private(self, job, message: str, *, retry: bool = False) -> None:
        if self._closed.is_set():
            return
        interaction = job["interaction"]
        try:
            self.client.patch(f"/webhooks/{interaction['application_id']}/{interaction['token']}/messages/@original",
                              {"content": message, "components": _button(job["message_id"], retry=True) if retry else [],
                               "allowed_mentions": dict(_NO_MENTIONS)},
                              authenticated=False, timeout=10, retries=1)
        except Exception as exc:
            _safe_log("private seminar response", exc)

    def _success_prompt(self, record) -> None:
        if not record.get("prompt_id") or self._closed.is_set():
            return
        draft = record["draft"]
        summary = draft["summary"][:600] + ("…" if len(draft["summary"]) > 600 else "")
        content = (f"# 세미나\n**{_markdown_escape(draft['title'][:180])}**\n"
                   f"발표일 · {draft['presented_on']}\n\n{_markdown_escape(summary)}\n\n"
                   "등록 요청 완료. 공개 홈페이지의 세미나 자료실에 반영되기까지 잠시 기다려 주세요.")
        try:
            self.client.patch(f"/channels/{self.channel}/messages/{record['prompt_id']}", {
                "content": content, "flags": 4,
                "allowed_mentions": dict(_NO_MENTIONS),
                "components": [{"type": 1, "components": [
                    {"type": 2, "style": 2, "label": "등록 요청 완료", "disabled": True,
                     "custom_id": "seminar:open:" + record["message_id"]},
                    {"type": 2, "style": 5, "label": "세미나 자료실", "url": _WEBSITE}]}],
            }, timeout=10, retries=1)
        except Exception as exc:
            _safe_log("public seminar status", exc)

    def _submit(self, job) -> None:
        message_id = job["message_id"]
        try:
            fields = self._fields(job["interaction"].get("data", {}).get("components"))
            with self._lock:
                record = self._read(message_id)
                pending = record is not None and record["status"] == "pending"
                if pending:
                    record["draft"] = fields
                    self._save(record)
            if not pending:
                self._edit_private(job, "이 자료는 이미 처리됐거나 입력 요청이 종료됐습니다.")
                return
            validated = app.validate_seminar_fields(**fields)
        except app.IngestError:
            self._edit_private(job, "제목(180자 이하)·실제 발표일(YYYY-MM-DD)·요약(1,000자 이하)을 확인해 주세요. 입력 내용은 저장되었습니다.", retry=True)
            return
        if self._closed.is_set():
            return
        original = self.client.get(f"/channels/{self.channel}/messages/{message_id}")
        author = original.get("author", {}) if isinstance(original, dict) else {}
        if (not isinstance(original, dict) or _snowflake(original.get("id")) != message_id
                or _snowflake(author.get("id")) != record["author_id"] or author.get("bot") or original.get("webhook_id")
                or original.get("channel_id", self.channel) != self.channel):
            self._edit_private(job, "원본 자료와 작성자를 확인할 수 없습니다. 자료를 새 메시지로 다시 올려 주세요.", retry=True)
            return
        try:
            app.validate_attachments(original.get("attachments", []))
        except app.IngestError:
            self._edit_private(job, "원본 메시지의 첨부파일이 없거나 형식·개수·용량 제한을 벗어났습니다. 지원 형식의 발표 자료를 확인한 뒤 다시 입력하거나 새 메시지로 올려 주세요.", retry=True)
            return
        if self._closed.is_set():
            return
        app.queue_message(self.client, self.guild, self.channel, original, self.inbox, fields=validated)
        with self._lock:
            record = self._read(message_id)
            record["status"] = "queued"
            record["draft"] = validated
            self._save(record)
        self._success_prompt(record)
        self._edit_private(job, "등록 요청이 완료되었습니다. 발표자는 서버 닉네임으로 표시되며, 세미나 자료실에 곧 반영됩니다.")

    def _release(self, message_id: str) -> None:
        with self._lock:
            if message_id in self._inflight:
                self._inflight.remove(message_id)
                self._slots.release()

    def _work(self) -> None:
        while not self._closed.is_set():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if not self._closed.is_set():
                    self._submit(job)
            except Exception as exc:
                _safe_log("seminar submission", exc)
                status = getattr(exc, "status", None)
                if status in {401, 403}:
                    message = "봇이 자료에 접근할 권한이 없습니다. 관리자에게 채널 접근·메시지 읽기 권한을 확인해 달라고 요청한 뒤 다시 입력을 눌러 주세요."
                elif status == 404:
                    message = "원본 메시지나 첨부자료를 찾을 수 없습니다. 자료를 새 메시지로 다시 올려 주세요."
                else:
                    message = "자료 등록에 실패했습니다. 입력 내용은 저장되어 있으니 잠시 뒤 다시 입력을 눌러 주세요."
                self._edit_private(job, message, retry=True)
            finally:
                self._release(job["message_id"])
                self._jobs.task_done()

    def close(self) -> None:
        self._closed.set()
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            self._release(job["message_id"])
            self._jobs.task_done()
        if threading.current_thread() is not self._worker:
            self._worker.join(timeout=1)
