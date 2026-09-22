import hashlib
import http.client
import json
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from seminar_service import app


def png(red=30, metadata=False):
    header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    pixels = (b"\x00" + bytes([red, 90, 160, 255]) * 2) * 2
    result = b"\x89PNG\r\n\x1a\n" + app._png_chunk(b"IHDR", header)
    if metadata:
        result += app._png_chunk(b"tEXt", b"Comment\x00private camera metadata")
    return result + app._png_chunk(b"IDAT", zlib.compress(pixels)) + app._png_chunk(b"IEND", b"")


class PeopleProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.originals = {name: getattr(app, name) for name in ("DATA_DIR", "SITE_DIR")}
        app.DATA_DIR = self.root / "private-data"
        app.SITE_DIR = self.root / "site"
        (app.SITE_DIR / "js").mkdir(parents=True)
        self.roster = {"professor": {"id": "professor-lee"}, "members": [{"id": "member-han"}],
                       "alumni": [{"id": "alumni-kim"}]}
        self.write_roster()
        app.ADMIN_SESSIONS.clear()
        app.ADMIN_SESSIONS[hashlib.sha256(b"profiles-test-session").hexdigest()] = time.time() + 1000
        self.cookie = "ailab_admin=profiles-test-session"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        app.ADMIN_SESSIONS.clear()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temporary.cleanup()

    def write_roster(self):
        (app.SITE_DIR / "js" / "data.js").write_text(
            "/* Test roster */\nwindow.SITE_DATA = " + json.dumps(self.roster) + ";\n", encoding="utf-8")

    def request(self, path, method="GET", body=None, authenticated=True, origin=None, content_type=None):
        headers = {}
        if authenticated:
            headers["Cookie"] = self.cookie
        if origin is not None:
            headers["Origin"] = origin
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            content = json.loads(raw) if response.headers.get("Content-Type", "").startswith("application/json") else raw
            return response.status, content, response.headers

    def upload(self, person="member-han", image=None):
        return self.request(f"/api/admin/people/{person}/photo", "POST", png() if image is None else image,
                            content_type="image/png")

    def test_links_and_photos_persist_outside_site_and_preserve_each_other(self):
        status, value, _ = self.request("/api/people-profiles", authenticated=False)
        self.assertEqual((status, value), (200, {"version": 1, "profiles": {}}))
        links = {"github": "https://github.com/han", "linkedin": "https://kr.linkedin.com/in/han",
                 "website": "https://example.org/?a=1&name=한찬식"}
        status, value, _ = self.request("/api/admin/people/member-han", "PUT", {"links": links}, origin=self.base)
        self.assertEqual(status, 200)
        self.assertEqual(value["profile"], {"links": links, "photo": ""})
        status, value, _ = self.upload(image=png(metadata=True))
        self.assertEqual(status, 200)
        photo = value["profile"]["photo"]
        self.assertEqual(value["profile"]["links"], links)
        self.assertRegex(photo, r"^/people-photos/[a-f0-9]{32}\.png$")
        status, image, headers = self.request(photo, authenticated=False)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(b"private camera metadata", image)
        self.assertEqual(app._normalize_people_png(image), image)
        self.assertEqual(self.request(photo, "HEAD")[0:2], (200, b""))
        links["website"] = "https://new.example.org/"
        status, value, _ = self.request("/api/admin/people/member-han", "PUT", {"links": links})
        self.assertEqual(value["profile"]["photo"], photo)
        self.assertTrue((app.DATA_DIR / "people" / "photos" / photo.rsplit("/", 1)[-1]).is_file())
        self.assertFalse(any(path.suffix == ".png" for path in app.SITE_DIR.rglob("*")))
        # Rereading persisted JSON and a replacement deployed data.js keeps the override.
        self.write_roster()
        saved = self.request("/api/people-profiles", authenticated=False)[1]["profiles"]["member-han"]
        self.assertEqual(saved, {"links": links, "photo": photo})
        self.assertEqual(self.request("/people/profiles.json")[0], 404)
        self.assertEqual(self.request("/seminar-data/people/profiles.json")[0], 404)

    def test_mutations_require_admin_and_same_origin_and_known_id(self):
        for method, suffix, body, kind in [("PUT", "", {"links": {}}, None),
                                            ("POST", "/photo", png(), "image/png"),
                                            ("DELETE", "/photo", None, None)]:
            path = "/api/admin/people/member-han" + suffix
            with self.subTest(method=method):
                self.assertEqual(self.request(path, method, body, False, content_type=kind)[0], 401)
                self.assertEqual(self.request(path, method, body, origin="https://evil.example", content_type=kind)[0], 403)
                self.assertEqual(self.request(path, method, body, origin="http://[broken", content_type=kind)[0], 403)
                self.assertEqual(self.request(path, method, body, origin=self.base.replace("http:", "https:"),
                                              content_type=kind)[0], 403)
                self.assertEqual(self.request(path.replace("member-han", "nobody"), method, body,
                                              content_type=kind)[0], 404)
        self.assertEqual(self.request("/api/people-profiles")[1]["profiles"], {})
        for person in ("professor-lee", "alumni-kim"):
            self.assertEqual(self.request("/api/admin/people/" + person, "PUT", {"links": {}})[0], 200)

    def test_urls_reject_active_content_credentials_and_fake_service_domains(self):
        invalid = [("website", "javascript:alert(1)"), ("website", "data:text/html,x"),
                   ("website", "https://user:password@example.org/"), ("website", "//example.org/"),
                   ("website", "https://example.org/\n<script>"), ("website", "https://example.org/%0d%0aX:1"),
                   ("website", "https://example.org/\" onclick=alert(1)"), ("website", "https://bad_host.org/"),
                   ("website", "https://example.org:99999/"), ("website", "https://example.org\\evil/"),
                   ("github", "https://github.com.evil.org/user"), ("github", "https://evil.org/github.com"),
                   ("linkedin", "https://notlinkedin.com/user"), ("linkedin", "https://linkedin.com.evil.org/user")]
        for service, url in invalid:
            with self.subTest(url=url):
                self.assertEqual(self.request("/api/admin/people/member-han", "PUT", {"links": {service: url}})[0], 400)
        for body in ({}, {"links": "invalid"}, {"links": {"unknown": ""}}, {"links": {"website": 12}},
                     {"links": {"website": "https://example.org/" + "a" * 2048}}):
            self.assertEqual(self.request("/api/admin/people/member-han", "PUT", body)[0], 400)
        self.assertEqual(self.request("/api/people-profiles")[1]["profiles"], {})

    def test_photo_validation_rejects_non_images_corruption_trailing_data_and_bombs(self):
        huge_header = struct.pack(">IIBBBBB", 1201, 2, 8, 6, 0, 0, 0)
        normal_header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
        signature = b"\x89PNG\r\n\x1a\n"
        malicious = [b"<svg onload='alert(1)'/>", b"<html>unsafe</html>", b"\xff\xd8\xffjpeg",
                     png()[:-1], png() + b"<script>alert(1)</script>",
                     signature + app._png_chunk(b"IHDR", huge_header) + app._png_chunk(b"IEND", b""),
                     signature + app._png_chunk(b"IHDR", normal_header)
                     + app._png_chunk(b"IDAT", zlib.compress(b"\x00" * 1_000_000)) + app._png_chunk(b"IEND", b"")]
        corrupt = bytearray(png())
        corrupt[25] ^= 1
        malicious.append(bytes(corrupt))
        for image in malicious:
            self.assertEqual(self.upload(image=image)[0], 400)
        self.assertEqual(self.request("/api/admin/people/member-han/photo", "POST", png(), content_type="image/svg+xml")[0], 400)
        self.assertEqual(self.request("/api/people-profiles")[1]["profiles"], {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", "/api/admin/people/member-han/photo", body=None,
                               headers={"Cookie": self.cookie, "Content-Type": "image/png",
                                        "Content-Length": str(app.PEOPLE_PHOTO_MAX_BYTES + 1)})
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()

    def test_replaced_deleted_and_removed_roster_photos_are_not_public(self):
        self.request("/api/admin/people/member-han", "PUT", {"links": {"website": "https://example.org/han"}})
        first = self.upload()[1]["profile"]["photo"]
        with patch.object(app, "_remove_people_photo"):
            second = self.upload(image=png(red=90))[1]["profile"]["photo"]
        self.assertNotEqual(first, second)
        self.assertTrue((app.DATA_DIR / "people" / "photos" / first.rsplit("/", 1)[-1]).exists())
        self.assertEqual(self.request(first)[0], 404)
        self.assertEqual(self.request(second)[0], 200)
        with patch.object(app, "_remove_people_photo"):
            status, result, _ = self.request("/api/admin/people/member-han/photo", "DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(result["profile"]["photo"], "")
        self.assertEqual(result["profile"]["links"]["website"], "https://example.org/han")
        self.assertEqual(self.request(second)[0], 404)
        photo = self.upload()[1]["profile"]["photo"]
        self.roster["members"] = []
        self.write_roster()
        self.assertEqual(self.request(photo)[0], 404)
        self.assertEqual(self.request("/api/people-profiles")[1]["profiles"], {})

    def test_traversal_unregistered_file_and_symlink_are_not_served(self):
        photo = self.upload()[1]["profile"]["photo"]
        for path in ["/people-photos/../profiles.json", "/people-photos/%2e%2e%2fprofiles.json",
                     "/people-photos/", "/people-photos/" + "0" * 32 + ".png",
                     photo + "/more", photo + "%00"]:
            self.assertEqual(self.request(path)[0], 404)
        disk_photo = app.DATA_DIR / "people" / "photos" / photo.rsplit("/", 1)[-1]
        disk_photo.unlink()
        private = self.root / "private.txt"
        private.write_text("secret")
        disk_photo.symlink_to(private)
        self.assertEqual(self.request(photo)[0], 404)

    def test_failed_metadata_commit_keeps_old_photo_and_links(self):
        original = self.upload()[1]["profile"]
        photo_dir = app.DATA_DIR / "people" / "photos"
        old_files = {path.name for path in photo_dir.iterdir()}
        with patch.object(app, "_atomic_json", side_effect=OSError("simulated disk full")), self.assertLogs(app.LOG, level="ERROR"):
            self.assertEqual(self.upload(image=png(red=90))[0], 500)
            self.assertEqual(self.request("/api/admin/people/member-han/photo", "DELETE")[0], 500)
            self.assertEqual(self.request("/api/admin/people/member-han", "PUT", {"links": {"website": "https://new.example"}})[0], 500)
        self.assertEqual({path.name for path in photo_dir.iterdir()}, old_files)
        self.assertEqual(self.request("/api/people-profiles")[1]["profiles"]["member-han"], original)
        self.assertEqual(self.request(original["photo"])[0], 200)


if __name__ == "__main__":
    unittest.main()
