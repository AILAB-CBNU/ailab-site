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
        self.requests = 0
    def get(self, route):
        self.requests += 1
        return {'nick': '연구실 닉네임'}
    def download(self, url, path, budget):
        self.downloads += 1
        path.write_bytes(b'%PDF-1.4 test')
        return path.stat().st_size

class DiscordTests(unittest.TestCase):
    def message(self, mid='123', date='2026-09-22T01:00:00Z'):
        return {'id': mid, 'author': {'id': '456', 'username': 'account'},
                'timestamp': date, 'content': '#세미나\n제목: 시계열 예측 세미나\n발표일: 2026-09-22\n요약: 최신 논문의 핵심 기법을 소개합니다.',
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
                self.assertEqual(rows[0]['title'], '시계열 예측 세미나')
                self.assertEqual(rows[0]['summary'], '최신 논문의 핵심 기법을 소개합니다.')
                self.assertEqual(rows[0]['presented_on'], '2026-09-22')
                self.assertEqual(rows[0]['files'][0]['name'], '자료.pdf')
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

    def test_rejects_bad_templates_before_network_or_files(self):
        template = self.message()['content']
        invalid = [
            '', '아무 설명 없는 파일입니다.', template.replace('#세미나', '#seminar'),
            template.replace('제목: 시계열 예측 세미나\n', ''),
            template.replace('시계열 예측 세미나', ''),
            template.replace('2026-09-22', '2026-02-30'),
            template.replace('2026-09-22', '2026-9-22'),
            template + '\n제목: 중복 제목', template + '\n알 수 없는 줄',
            template.replace('시계열 예측 세미나', '가' * 181),
            template.replace('최신 논문의 핵심 기법을 소개합니다.', '가' * 1001),
        ]
        for content in invalid:
            with self.subTest(content=content[:40]), tempfile.TemporaryDirectory() as tmp:
                message = self.message()
                message['content'] = content
                client = FakeClient()
                with self.assertRaises(website.IngestError):
                    app.queue_message(client, '1', '2', message, Path(tmp))
                self.assertEqual(client.requests, 0)
                self.assertEqual(client.downloads, 0)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_requires_attachment_for_seminar_but_ignores_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self.message()
            message['attachments'] = []
            client = FakeClient()
            with self.assertRaisesRegex(website.IngestError, 'FORMAT_ATTACHMENT'):
                app.queue_message(client, '1', '2', message, Path(tmp))
            message['content'] = '안녕하세요'
            self.assertFalse(app.queue_message(client, '1', '2', message, Path(tmp)))
            self.assertEqual(client.requests, 0)

    def test_template_allows_blank_lines_and_korean_colons_in_summary(self):
        fields = app.parse_seminar_message('\n#세미나\n\n제목: 한글 제목\n발표일: 2024-02-29\n요약: 방법: 시계열 예측\n')
        self.assertEqual(fields['summary'], '방법: 시계열 예측')
        self.assertEqual(fields['presented_on'], '2024-02-29')

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
