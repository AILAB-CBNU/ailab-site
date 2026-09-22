import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from discord_sync import app
from discord_sync.interactions import InteractiveSeminars
from seminar_service import app as website


class FakeClient:
    def __init__(self):
        self.messages = {}
        self.posts, self.patches, self.gets, self.downloads, self.events = [], [], [], [], []
        self.fail_prompt = None
        self.fail_ack = None
        self.fail_fetch = None
        self.fail_download = None
        self.download_started = threading.Event()
        self.download_gate = None
        self.nonces = {}

    def post(self, route, payload, **options):
        self.posts.append((route, copy.deepcopy(payload), options))
        self.events.append(("post", route, payload.get("type")))
        if route.startswith("/interactions/"):
            if self.fail_ack:
                raise self.fail_ack
            return None
        nonce = payload["nonce"]
        self.nonces.setdefault(nonce, str(9000 + len(self.nonces)))
        if self.fail_prompt:
            raise self.fail_prompt
        return {"id": self.nonces[nonce]}

    def patch(self, route, payload, **options):
        self.patches.append((route, copy.deepcopy(payload), options))
        self.events.append(("patch", route, None))
        return {"id": "9000"}

    def get(self, route):
        self.gets.append(route)
        self.events.append(("get", route, None))
        if route.startswith("/channels/"):
            if self.fail_fetch:
                raise self.fail_fetch
            return copy.deepcopy(self.messages[route.rsplit("/", 1)[-1]])
        return {"nick": "연구실 닉네임"}

    def download(self, url, path, budget):
        self.downloads.append(url)
        self.events.append(("download", "redacted", None))
        self.download_started.set()
        if self.download_gate is not None and not self.download_gate.wait(timeout=5):
            raise TimeoutError("test download gate timeout")
        if self.fail_download:
            raise self.fail_download
        path.write_bytes(b"%PDF-1.4 test")
        return path.stat().st_size


class DiscordInteractionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state, self.inbox = self.root / "state", self.root / "inbox"
        self.client = FakeClient()
        self.service = InteractiveSeminars(self.client, "100", "200", self.state, self.inbox)
        self.serial = 500
        self.message = self.make_message()

    def tearDown(self):
        if self.client.download_gate is not None:
            self.client.download_gate.set()
        self.service.close()
        self.temporary.cleanup()

    def make_message(self, message_id="123"):
        message = {"id": message_id, "channel_id": "200", "guild_id": "100",
                   "author": {"id": "300", "username": "account"}, "content": "",
                   "timestamp": "2026-09-22T01:00:00Z",
                   "attachments": [{"filename": "발표자료.pdf", "size": 13,
                                    "url": "https://cdn.discordapp.com/attachments/1/2/file.pdf?hm=CDN_SECRET"}]}
        self.client.messages[message_id] = message
        return message

    def record(self, message_id="123"):
        return json.loads((self.state / "forms" / (message_id + ".json")).read_text(encoding="utf-8"))

    def interaction(self, action="open", message_id="123", fields=None):
        self.serial += 1
        data = {"custom_id": f"seminar:{action}:{message_id}"}
        if action == "submit":
            fields = fields if fields is not None else {"title": "시계열 연구 세미나", "presented_on": "2026-09-22", "summary": "첫 번째 줄\n두 번째 줄"}
            data["components"] = [{"type": 18, "component": {"type": 4, "custom_id": key, "value": value}}
                                  for key, value in fields.items()]
        return {"id": str(self.serial), "application_id": "400", "token": "TOKEN_SECRET_" + str(self.serial),
                "type": 5 if action == "submit" else 3, "guild_id": "100", "channel_id": "200",
                "member": {"user": {"id": "300"}}, "message": {"id": self.record(message_id)["prompt_id"]}, "data": data}

    def wait_idle(self):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.service._jobs.unfinished_tasks == 0 and not self.service._inflight:
                return
            time.sleep(0.01)
        self.fail("seminar worker did not finish")

    def callback(self):
        return next(row for row in reversed(self.client.posts) if row[0].startswith("/interactions/"))

    def test_offer_modal_submit_creates_manifest_only_after_ack_and_valid_submission(self):
        self.assertTrue(self.service.offer(self.message))
        self.assertFalse(self.inbox.exists())
        self.assertEqual(self.client.gets, [])
        self.assertEqual(self.client.downloads, [])
        route, reply, options = self.client.posts[0]
        self.assertEqual(route, "/channels/200/messages")
        self.assertEqual(reply["message_reference"], {"message_id": "123", "fail_if_not_exists": True})
        self.assertEqual(reply["nonce"], "s123")
        self.assertTrue(reply["enforce_nonce"])
        self.assertEqual(reply["allowed_mentions"], {"parse": [], "replied_user": False})
        self.assertEqual(reply["components"][0]["components"][0]["custom_id"], "seminar:open:123")
        self.assertIn("공개 홈페이지", reply["content"])
        self.service.handle(self.interaction())
        route, response, options = self.callback()
        self.assertEqual(response["type"], 9)
        self.assertEqual(response["data"]["custom_id"], "seminar:submit:123")
        self.assertEqual(response["data"]["title"], "세미나 정보 입력")
        labels = response["data"]["components"]
        self.assertEqual([row["type"] for row in labels], [18, 18, 18])
        self.assertEqual([row["component"]["max_length"] for row in labels], [180, 10, 1000])
        self.assertEqual(labels[-1]["component"]["style"], 2)
        self.assertEqual(options, {"authenticated": False, "timeout": 2.5, "retries": 1})
        self.assertFalse(self.inbox.exists())
        self.service.handle(self.interaction("submit"))
        self.wait_idle()
        manifest = json.loads((self.inbox / "discord-200-123.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["title"], "시계열 연구 세미나")
        self.assertEqual(manifest["summary"], "첫 번째 줄 두 번째 줄")
        self.assertEqual(manifest["uploaded_at"], self.message["timestamp"])
        self.assertEqual(manifest["presenter_discord"], "연구실 닉네임")
        self.assertEqual(manifest["source_message_id"], "discord:100:200:123")
        self.assertEqual(self.record()["status"], "queued")
        ack_index = next(i for i, event in enumerate(self.client.events) if event[0] == "post" and event[2] == 5)
        get_index = next(i for i, event in enumerate(self.client.events) if event[0] == "get")
        download_index = next(i for i, event in enumerate(self.client.events) if event[0] == "download")
        self.assertLess(ack_index, get_index)
        self.assertLess(get_index, download_index)
        public = next(row for row in self.client.patches if row[0].startswith("/channels/"))
        self.assertTrue(public[1]["components"][0]["components"][0]["disabled"])
        private = next(row for row in self.client.patches if row[0].startswith("/webhooks/"))
        self.assertFalse(private[2]["authenticated"])
        self.assertEqual(private[1]["allowed_mentions"]["parse"], [])
        contents = "\n".join(path.read_text(encoding="utf-8") for path in (self.state / "forms").glob("*.json"))
        for secret in ("TOKEN_SECRET", "CDN_SECRET", "https://cdn.discordapp.com", "attachments"):
            self.assertNotIn(secret, contents)
        data_dir = self.root / "website-data"
        data_dir.mkdir()
        with patch.multiple(website, DATA_DIR=data_dir, INDEX_PATH=data_dir / "index.json",
                            ITEMS_DIR=data_dir / "items", INBOX_DIR=self.inbox):
            website._process_inbox_manifest(self.inbox / "discord-200-123.json")
            rows = website._read_index()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "시계열 연구 세미나")
            self.assertEqual(rows[0]["presenter"], "연구실 닉네임")
            self.assertEqual(rows[0]["presented_on"], "2026-09-22")
            self.assertEqual(rows[0]["uploaded_at"], self.message["timestamp"])

    def test_invalid_date_saves_draft_and_retry_survives_restart_without_auto_submission(self):
        self.service.offer(self.message)
        draft = {"title": "유지할 제목", "presented_on": "2026-02-30", "summary": "여러 줄\n요약 유지"}
        self.service.handle(self.interaction("submit", fields=draft))
        self.wait_idle()
        self.assertEqual(self.record()["draft"], draft)
        self.assertEqual(self.record()["status"], "pending")
        self.assertEqual(self.client.gets, [])
        self.assertEqual(self.client.downloads, [])
        self.assertFalse(self.inbox.exists())
        retry = self.client.patches[-1][1]["components"][0]["components"][0]
        self.assertEqual(retry["custom_id"], "seminar:retry:123")
        self.service.close()
        self.service = InteractiveSeminars(self.client, "100", "200", self.state, self.inbox)
        count = len(self.client.posts)
        self.assertTrue(self.service.offer(self.message))
        self.assertEqual(len(self.client.posts), count)
        self.assertEqual(self.client.gets, [])
        request = self.interaction("retry")
        request["message"]["id"] = "88888"  # Private retry is not the public prompt.
        self.service.handle(request)
        modal = self.callback()[1]
        self.assertEqual(modal["type"], 9)
        actual = {label["component"]["custom_id"]: label["component"].get("value") for label in modal["data"]["components"]}
        self.assertEqual(actual, draft)
        draft["presented_on"] = "2026-02-28"
        self.service.handle(self.interaction("submit", fields=draft))
        self.wait_idle()
        self.assertEqual(self.record()["status"], "queued")
        self.assertEqual(len(self.client.downloads), 1)

    def test_other_users_guilds_channels_prompt_ids_and_malformed_actions_are_private_rejections(self):
        self.service.offer(self.message)
        requests = []
        for key in ("guild_id", "channel_id"):
            request = self.interaction()
            request[key] = "9999"
            requests.append(request)
        request = self.interaction()
        request["member"]["user"]["id"] = "9999"
        requests.append(request)
        request = self.interaction()
        request["message"]["id"] = "9999"
        requests.append(request)
        request = self.interaction("submit")
        request["member"]["user"]["id"] = "9999"
        requests.append(request)
        request = self.interaction()
        request["data"]["custom_id"] = "seminar:open:../../escape"
        requests.append(request)
        request = self.interaction()
        request["data"]["custom_id"] = "seminar:open:9999"
        requests.append(request)
        for request in requests:
            with self.subTest(request=request["id"]):
                self.service.handle(request)
                response = self.callback()[1]
                self.assertEqual(response["type"], 4)
                self.assertEqual(response["data"]["flags"], 64)
                self.assertEqual(response["data"]["allowed_mentions"]["parse"], [])
        self.assertEqual(self.client.gets, [])
        self.assertEqual(self.client.downloads, [])
        self.assertFalse(self.inbox.exists())

    def test_double_submission_never_downloads_twice_and_does_not_block_callbacks(self):
        self.service.offer(self.message)
        self.client.download_gate = threading.Event()
        self.service.handle(self.interaction("submit"))
        self.assertTrue(self.client.download_started.wait(timeout=2))
        self.service.handle(self.interaction("submit"))
        response = self.callback()[1]
        self.assertEqual(response["type"], 4)
        self.assertIn("처리하고", response["data"]["content"])
        self.assertFalse((self.inbox / "discord-200-123.json").exists())
        self.client.download_gate.set()
        self.wait_idle()
        self.service.handle(self.interaction("submit"))
        self.assertEqual(self.callback()[1]["type"], 4)
        self.assertEqual(len(self.client.downloads), 1)
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 1)

    def test_download_failure_keeps_draft_and_can_retry_without_leaking_exception_secrets(self):
        self.service.offer(self.message)
        self.client.fail_download = RuntimeError("TOKEN_SECRET https://cdn.discordapp.com/?hm=CDN_SECRET")
        with self.assertLogs("discord-seminar-forms", level="WARNING") as logs:
            self.service.handle(self.interaction("submit"))
            self.wait_idle()
        self.assertNotIn("SECRET", "\n".join(logs.output))
        self.assertEqual(self.record()["status"], "pending")
        self.assertEqual(self.record()["draft"]["title"], "시계열 연구 세미나")
        self.assertEqual(list(self.inbox.glob("*.json")), [])
        self.assertEqual(self.client.patches[-1][1]["components"][0]["components"][0]["custom_id"], "seminar:retry:123")
        self.client.fail_download = None
        self.service.handle(self.interaction("submit"))
        self.wait_idle()
        self.assertEqual(self.record()["status"], "queued")
        self.assertTrue((self.inbox / "discord-200-123.json").exists())

    def test_fetch_permission_error_does_not_retry_indefinitely_or_download(self):
        self.service.offer(self.message)
        self.client.fail_fetch = app.ApiError(403)
        with self.assertLogs("discord-seminar-forms", level="WARNING"):
            self.service.handle(self.interaction("submit"))
            self.wait_idle()
        self.assertEqual(len(self.client.gets), 1)
        self.assertEqual(self.client.downloads, [])
        self.assertIn("권한", self.client.patches[-1][1]["content"])
        self.assertEqual(self.record()["status"], "pending")

    def test_changed_author_bot_or_removed_attachments_do_not_publish(self):
        self.service.offer(self.message)
        bad_messages = []
        changed = copy.deepcopy(self.message)
        changed["author"]["id"] = "666"
        bad_messages.append(changed)
        changed = copy.deepcopy(self.message)
        changed["author"]["bot"] = True
        bad_messages.append(changed)
        changed = copy.deepcopy(self.message)
        changed["attachments"] = []
        bad_messages.append(changed)
        for changed in bad_messages:
            self.client.messages["123"] = changed
            self.service.handle(self.interaction("submit"))
            self.wait_idle()
            self.assertEqual(self.record()["status"], "pending")
            self.assertEqual(self.client.downloads, [])
            self.assertFalse(self.inbox.exists())

    def test_invalid_files_get_one_fixed_reply_without_form_or_download(self):
        self.message["attachments"][0]["filename"] = "SECRET_NAME.exe"
        self.assertTrue(self.service.offer(self.message))
        self.assertTrue(self.service.offer(self.message))
        self.assertEqual(len(self.client.posts), 1)
        reply = self.client.posts[0][1]
        self.assertEqual(reply["components"], [])
        self.assertNotIn("SECRET_NAME", reply["content"])
        self.assertEqual(reply["allowed_mentions"]["replied_user"], False)
        self.assertEqual(self.record()["status"], "rejected")
        self.assertEqual(self.client.downloads, [])
        self.assertFalse(self.inbox.exists())
        for changes in ({"author": {"id": "300", "bot": True}}, {"webhook_id": "777"}, {"attachments": []}):
            message = dict(self.message, **changes)
            self.assertFalse(self.service.offer(message))
        self.assertEqual(len(self.client.posts), 1)

    def test_failed_prompt_retry_reuses_nonce_and_failed_ack_never_downloads(self):
        self.client.fail_prompt = app.ApiError(403)
        with self.assertRaises(app.ApiError):
            self.service.offer(self.message)
        self.assertEqual(self.record()["prompt_id"], "")
        self.client.fail_prompt = None
        self.service.offer(self.message)
        self.assertEqual([row[1]["nonce"] for row in self.client.posts], ["s123", "s123"])
        self.assertEqual(len(self.client.nonces), 1)
        self.client.fail_ack = TimeoutError("TOKEN_SECRET")
        with self.assertLogs("discord-seminar-forms", level="WARNING") as logs:
            self.service.handle(self.interaction("submit"))
        self.assertNotIn("SECRET", "\n".join(logs.output))
        self.assertEqual(self.client.gets, [])
        self.assertEqual(self.service._inflight, set())
        self.assertFalse(self.inbox.exists())
        self.client.fail_ack = None
        self.service.handle(self.interaction("submit"))
        self.wait_idle()
        self.assertEqual(self.record()["status"], "queued")

    def test_success_reply_escapes_markdown_mentions_and_stays_within_discord_limit(self):
        self.service.offer(self.message)
        fragment = r"*bold*_~`|[]()>#\\@everyone"
        fields = {"title": (fragment * 20)[:180], "presented_on": "2026-09-22", "summary": (fragment * 100)[:1000]}
        self.service.handle(self.interaction("submit", fields=fields))
        self.wait_idle()
        public = next(row[1] for row in self.client.patches if row[0].startswith("/channels/"))
        self.assertTrue(public["content"].startswith("# 세미나\n**\\*bold\\*"))
        self.assertIn("발표일 · 2026-09-22", public["content"])
        self.assertNotIn("@everyone", public["content"])
        self.assertIn("@\u200beveryone", public["content"])
        self.assertLessEqual(len(public["content"]), 2000)
        self.assertEqual(public["allowed_mentions"], {"parse": [], "replied_user": False})
        self.assertEqual(public["flags"], 4)  # No URL embeds from user-provided summaries.
        manifest = json.loads((self.inbox / "discord-200-123.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["summary"], fields["summary"])

    def test_existing_processed_manifest_is_not_downloaded_again_after_interrupted_status_save(self):
        self.service.offer(self.message)
        self.service.handle(self.interaction("submit"))
        self.wait_idle()
        manifest = self.inbox / "discord-200-123.json"
        (self.inbox / ".processed").mkdir()
        manifest.replace(self.inbox / ".processed" / manifest.name)
        record = self.record()
        record["status"] = "pending"
        (self.state / "forms" / "123.json").write_text(json.dumps(record), encoding="utf-8")
        self.service.close()
        self.service = InteractiveSeminars(self.client, "100", "200", self.state, self.inbox)
        self.service.handle(self.interaction("submit"))
        self.wait_idle()
        self.assertEqual(len(self.client.downloads), 1)
        self.assertEqual(self.record()["status"], "queued")
        self.assertFalse(manifest.exists())

    def test_worker_queue_is_bounded_and_closed_service_does_not_offer_or_submit(self):
        self.client.download_gate = threading.Event()
        for number in range(9):
            message_id = str(2000 + number)
            self.service.offer(self.make_message(message_id))
            self.service.handle(self.interaction("submit", message_id=message_id))
        self.assertEqual(len(self.service._inflight), 8)
        self.assertEqual(self.callback()[1]["type"], 4)
        self.assertIn("요청이 많", self.callback()[1]["data"]["content"])
        self.assertLessEqual(self.service._jobs.qsize(), 8)
        self.client.download_gate.set()
        self.wait_idle()
        self.service.close()
        count = len(self.client.posts)
        self.assertFalse(self.service.offer(self.message))
        self.service.handle(self.interaction("submit", message_id="2008"))
        self.assertEqual(len(self.client.posts), count)


if __name__ == "__main__":
    unittest.main()
