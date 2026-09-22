import base64
import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

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

    def test_optional_presentation_date_preserves_legacy_ingest(self):
        record, _ = app.ingest(self.payload())
        self.assertEqual(record['presented_on'], '')
        payload = self.payload('new-format')
        payload['presented_on'] = '2024-02-29'
        record, _ = app.ingest(payload)
        self.assertEqual(record['presented_on'], '2024-02-29')
        for value in ['2026-02-29', '2026-9-22', '2026-09-22T12:00:00Z']:
            payload = self.payload('bad-' + value)
            payload['presented_on'] = value
            with self.assertRaises(app.IngestError):
                app.ingest(payload)

    def test_delete_keeps_private_copy_and_blocks_replay(self):
        record, _ = app.ingest(self.payload())
        self.assertTrue(app.delete_seminar(record['id']))
        self.assertEqual(app._read_index(), [])
        self.assertFalse((app.ITEMS_DIR / record['id']).exists())
        self.assertEqual((app.DATA_DIR / 'trash' / record['id'] / 'slides.pdf').read_bytes(), b'PDF test')
        self.assertTrue(app._deletion_path(record['source_message_id']).exists())
        self.assertFalse(app.delete_seminar(record['id']))
        with self.assertRaises(app.DeletedSeminarError):
            app.ingest(self.payload())
        # An old queued manifest is retired, even if its attachment was removed.
        payload = self.payload()
        payload['files'] = [{'name': 'slides.pdf', 'path': 'missing.pdf'}]
        manifest = app.INBOX_DIR / 'replay.json'
        manifest.write_text(json.dumps(payload), encoding='utf-8')
        app._process_inbox_manifest(manifest)
        self.assertTrue((app.INBOX_DIR / '.processed' / 'replay.json').exists())
        self.assertEqual(app._read_index(), [])
        replacement, created = app.ingest(self.payload('new-message-id'))
        self.assertTrue(created)
        self.assertNotEqual(record['id'], replacement['id'])

    def test_delete_commit_survives_interrupted_cleanup(self):
        record, _ = app.ingest(self.payload())
        with patch.object(app, '_finalize_deletion', side_effect=OSError('simulated open Windows file')):
            self.assertTrue(app.delete_seminar(record['id']))
        self.assertEqual(app._read_index(), [])
        self.assertTrue((app.ITEMS_DIR / record['id']).is_dir())
        with self.assertRaises(app.DeletedSeminarError):
            app.ingest(self.payload())
        app._ensure_layout()
        self.assertFalse((app.ITEMS_DIR / record['id']).exists())
        self.assertTrue((app.DATA_DIR / 'trash' / record['id'] / 'slides.pdf').exists())

    def test_failed_delete_commit_leaves_item_intact(self):
        record, _ = app.ingest(self.payload())
        with patch.object(app, '_atomic_json', side_effect=OSError('simulated disk full')):
            with self.assertRaises(OSError):
                app.delete_seminar(record['id'])
        self.assertEqual(app._read_index()[0]['id'], record['id'])
        self.assertTrue((app.ITEMS_DIR / record['id'] / 'slides.pdf').is_file())
        self.assertFalse(app._deletion_path(record['source_message_id']).exists())

    def test_http_delete_requires_admin_origin_and_hides_file_after_commit(self):
        record, _ = app.ingest(self.payload())
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        target = base + '/api/admin/seminars/' + record['id']
        cookie = 'ailab_admin=test-admin-session'
        app.ADMIN_SESSIONS[hashlib.sha256(b'test-admin-session').hexdigest()] = time.time() + 1000
        try:
            for headers, expected in [({}, 401), ({'Cookie': cookie, 'Origin': 'https://evil.test'}, 403),
                                      ({'Cookie': cookie, 'Origin': base.replace('http:', 'https:')}, 403)]:
                request = urllib.request.Request(target, headers=headers, method='DELETE')
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(caught.exception.code, expected)
            with urllib.request.urlopen(base + record['files'][0]['url'], timeout=5) as response:
                self.assertEqual(response.read(), b'PDF test')
            # Prove the URL is blocked even while the file has not yet moved.
            with patch.object(app, '_finalize_deletion', side_effect=OSError('simulated crash')):
                request = urllib.request.Request(target, headers={'Cookie': cookie, 'Origin': base}, method='DELETE')
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(json.load(response), {'ok': True})
            self.assertTrue((app.ITEMS_DIR / record['id'] / 'slides.pdf').exists())
            with urllib.request.urlopen(base + '/api/seminars', timeout=5) as response:
                self.assertEqual(json.load(response), [])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + record['files'][0]['url'], timeout=5)
            self.assertEqual(caught.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

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
