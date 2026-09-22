import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from seminar_service import app


class SeminarServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.originals = {
            name: getattr(app, name)
            for name in (
                "DATA_DIR",
                "INDEX_PATH",
                "ITEMS_DIR",
                "INBOX_DIR",
                "PRESENTER_MAP_PATH",
                "UPLOAD_TOKEN",
                "ADMIN_AUTH_PATH",
                "CONTENT_OVERRIDES_PATH",
            )
        }
        app.DATA_DIR = root / "data"
        app.INDEX_PATH = app.DATA_DIR / "index.json"
        app.ITEMS_DIR = app.DATA_DIR / "items"
        app.INBOX_DIR = root / "inbox"
        app.PRESENTER_MAP_PATH = root / "presenter-map.json"
        app.ADMIN_AUTH_PATH = app.DATA_DIR / "admin-auth.json"
        app.CONTENT_OVERRIDES_PATH = app.DATA_DIR / "site-content-overrides.json"
        app.UPLOAD_TOKEN = "test-token"
        app.ADMIN_SESSIONS.clear()
        app.ADMIN_FAILURES.clear()
        app.PRESENTER_MAP_PATH.write_text(
            json.dumps({"by_teams_user_id": {"teams-user-1": "발표자닉네임"}, "by_email": {}}),
            encoding="utf-8",
        )
        app._ensure_layout()

    def tearDown(self):
        app.ADMIN_SESSIONS.clear()
        app.ADMIN_FAILURES.clear()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temporary.cleanup()

    @staticmethod
    def payload(message_id="message-1", uploaded_at="2026-09-16T08:00:00Z"):
        return {
            "source": "test",
            "source_message_id": message_id,
            "source_user_id": "teams-user-1",
            "title": "주간 세미나",
            "summary": "테스트 자료",
            "uploaded_at": uploaded_at,
            "files": [{"name": "slides.pdf", "content_base64": base64.b64encode(b"PDF test").decode("ascii")}],
        }

    def test_ingest_maps_presenter_sorts_and_deduplicates(self):
        first, created = app.ingest(self.payload())
        self.assertTrue(created)
        self.assertEqual(first["presenter"], "발표자닉네임")
        self.assertEqual((app.ITEMS_DIR / first["id"] / "slides.pdf").read_bytes(), b"PDF test")

        newer, created = app.ingest(self.payload("message-2", "2026-09-17T08:00:00Z"))
        self.assertTrue(created)
        duplicate, created = app.ingest(self.payload())
        self.assertFalse(created)
        self.assertEqual(duplicate["id"], first["id"])
        self.assertEqual([row["id"] for row in app._read_index()], [newer["id"], first["id"]])

    def test_http_ingest_requires_token_and_exposes_archive(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        body = json.dumps(self.payload()).encode("utf-8")
        try:
            unauthorized = urllib.request.Request(
                base + "/api/ingest", data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(unauthorized, timeout=5)
            self.assertEqual(caught.exception.code, 401)

            request = urllib.request.Request(
                base + "/api/ingest",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer test-token"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 201)
            with urllib.request.urlopen(base + "/api/seminars", timeout=5) as response:
                rows = json.load(response)
            self.assertEqual(rows[0]["presenter"], "발표자닉네임")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_admin_login_protects_and_persists_content_overrides(self):
        app.configure_admin_password("correct horse battery staple")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            unauthorized = urllib.request.Request(
                base + "/api/admin/content",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(unauthorized, timeout=5)
            self.assertEqual(caught.exception.code, 401)

            login = urllib.request.Request(
                base + "/api/admin/login",
                data=json.dumps({"password": "correct horse battery staple"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(login, timeout=5) as response:
                cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                self.assertEqual(response.status, 200)

            content = app._empty_content_overrides()
            content["pages"]["index.html"] = {"ko": {"#hero-title/text[0]": "새 연구실 이름"}, "en": {}}
            update = urllib.request.Request(
                base + "/api/admin/content",
                data=json.dumps(content, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Cookie": cookie},
                method="PUT",
            )
            with urllib.request.urlopen(update, timeout=5) as response:
                self.assertEqual(response.status, 200)

            with urllib.request.urlopen(base + "/api/content-overrides", timeout=5) as response:
                saved = json.load(response)
            self.assertEqual(saved["pages"]["index.html"]["ko"]["#hero-title/text[0]"], "새 연구실 이름")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
