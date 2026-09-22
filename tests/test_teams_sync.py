import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teams_sync import app


class FakeClient:
    def download(self, url):
        return b"teams file"


class TeamsSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.originals = {name: getattr(app, name) for name in ("INBOX_DIR", "STATE_DIR", "STATE_PATH")}
        app.INBOX_DIR = root / "inbox"
        app.STATE_DIR = root / "state"
        app.STATE_PATH = app.STATE_DIR / "state.json"
        app.INBOX_DIR.mkdir()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temporary.cleanup()

    @staticmethod
    def message():
        return {
            "id": "message-123",
            "createdDateTime": "2026-09-16T08:00:00Z",
            "subject": "9월 3주차 세미나",
            "from": {"user": {"id": "teams-user-1", "displayName": "홍길동"}},
            "body": {"contentType": "html", "content": "<p>멀티모달 모델 논문 리뷰</p><attachment id='a'></attachment>"},
            "attachments": [
                {
                    "contentType": "reference",
                    "contentUrl": "https://example.sharepoint.com/sites/lab/slides.pdf",
                    "name": "slides.pdf",
                }
            ],
        }

    def test_queue_writes_files_before_atomic_manifest(self):
        item = {
            "id": "drive-item",
            "name": "slides.pdf",
            "size": 10,
            "@microsoft.graph.downloadUrl": "https://download.example/file",
        }
        with mock.patch.object(app, "_drive_item", return_value=item):
            queued = app._queue_message(FakeClient(), {"id": "folder", "parentReference": {"driveId": "drive"}}, self.message())
        self.assertTrue(queued)
        manifests = list(app.INBOX_DIR.glob("teams-*.json"))
        self.assertEqual(len(manifests), 1)
        payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["source_user_id"], "teams-user-1")
        self.assertEqual(payload["title"], "9월 3주차 세미나")
        stored = app.INBOX_DIR / payload["files"][0]["path"]
        self.assertEqual(stored.read_bytes(), b"teams file")

    def test_first_poll_skips_existing_messages_by_default(self):
        with mock.patch.object(app, "_messages", return_value=[self.message()]), mock.patch.object(
            app, "IMPORT_EXISTING", False
        ), mock.patch.object(app, "_queue_message") as queue:
            app.poll_once(FakeClient())
        queue.assert_not_called()
        state = json.loads(app.STATE_PATH.read_text(encoding="utf-8"))
        self.assertTrue(state["initialized"])
        self.assertIn("message-123", state["processed"])

    def test_graph_client_separates_application_and_file_tokens(self):
        client = app.GraphClient()
        headers = []

        def capture(request, limit=None):
            headers.append(request.get_header("Authorization"))
            return b"{}"

        with mock.patch.object(client, "_application_access_token", return_value="app-token"), mock.patch.object(
            client, "_delegated_access_token", return_value="file-token"
        ), mock.patch.object(client, "_open", side_effect=capture):
            client.json("/teams/example/messages")
            client.json("/drives/example/items/example", delegated=True)

        self.assertEqual(headers, ["Bearer app-token", "Bearer file-token"])


if __name__ == "__main__":
    unittest.main()
