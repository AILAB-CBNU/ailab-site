import io
import urllib.error
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from discord_sync import app
from seminar_service import app as website

class FakeClient:
    def __init__(self):
        self.downloads = 0
    def get(self, route):
        return {'nick': '연구실 닉네임'}
    def download(self, url, path, budget):
        self.downloads += 1
        path.write_bytes(b'%PDF-1.4 test')
        return path.stat().st_size

class DiscordTests(unittest.TestCase):
    def message(self, mid='123', date='2026-09-22T01:00:00Z'):
        return {'id': mid, 'author': {'id': '456', 'username': 'account'},
                'timestamp': date, 'content': '세미나 제목\n요약',
                'attachments': [{'filename': '자료.pdf', 'url': 'unused', 'size': 13}]}

    def test_ingestion_nickname_date_sort_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / 'inbox'
            data = Path(tmp) / 'data'
            data.mkdir()
            with patch.multiple(website, INBOX_DIR=inbox, DATA_DIR=data, INDEX_PATH=data/'index.json', ITEMS_DIR=data/'items'):
                client = FakeClient()
                for mid, date in [('123', '2026-09-21T01:00:00Z'), ('124', '2026-09-22T01:00:00Z')]:
                    self.assertTrue(app.queue_message(client, '1', '2', self.message(mid, date), inbox))
                    manifest = inbox / f'discord-2-{mid}.json'
                    website._process_inbox_manifest(manifest)
                    self.assertFalse(app.queue_message(client, '1', '2', self.message(mid, date), inbox))
                rows = json.loads((data/'index.json').read_text())
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]['presenter'], '연구실 닉네임')
                self.assertTrue(rows[0]['source_message_id'].endswith(':124'))
                self.assertEqual(client.downloads, 2)

    def test_failed_download_never_publishes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            with patch.object(client, 'download', side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    app.queue_message(client, '1', '2', self.message(), Path(tmp))
            self.assertEqual(list(Path(tmp).glob('*.json')), [])
            self.assertTrue(app.queue_message(FakeClient(), '1', '2', self.message(), Path(tmp)))

    def test_pagination_catches_more_than_100_without_gaps(self):
        class Pages:
            def get(self, route):
                query = parse_qs(urlsplit(route).query)
                before = int(query.get('before', ['251'])[0])
                return [{'id': str(i)} for i in range(before-1, max(0, before-101), -1)]
        rows = app.new_messages(Pages(), '2', '10')
        self.assertEqual([int(r['id']) for r in rows], list(range(11, 251)))

    def test_attachment_http_error_redacts_signed_url(self):
        client = app.Client('SECRET_TOKEN')
        url = 'https://cdn.discordapp.com/attachments/1/2/a.pdf?hm=SECRET_SIGNATURE'
        with patch.object(client.opener, 'open', side_effect=urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)):
            with self.assertRaises(app.AttachmentError) as caught:
                client.download(url, Path('/unused'), 100)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.host, 'cdn.discordapp.com')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_download_user_agent_without_bot_token(self):
        client = app.Client('SECRET_TOKEN')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(client.opener, 'open', return_value=io.BytesIO(b'data')) as request:
                self.assertEqual(client.download('https://cdn.discordapp.com/attachments/1/2/a.pdf', Path(tmp)/'file', 100), 4)
                headers = dict(request.call_args.args[0].header_items())
                self.assertIn('User-agent', headers)
                self.assertNotIn('Authorization', headers)

    def test_blocks_unsafe_cdn_urls(self):
        client = app.Client('not-real')
        for url in ['http://cdn.discordapp.com/attachments/a', 'https://evil.test/attachments/a', 'https://cdn.discordapp.com.evil.test/attachments/a']:
            with self.assertRaises(ValueError):
                client.download(url, Path('/unused'), 100)

    def test_rejects_unsupported_files_before_download(self):
        message = self.message()
        message['attachments'][0]['filename'] = 'run.exe'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(website.IngestError):
                app.queue_message(FakeClient(), '1', '2', message, Path(tmp))

if __name__ == '__main__':
    unittest.main()
