import io
import urllib.error
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
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
    def message(self, mid='123', date='2026-09-22T01:00:00Z', heading='# 세미나'):
        return {'id': mid, 'author': {'id': '456', 'username': 'account'},
                'timestamp': date, 'content': heading + '\n제목: 시계열 예측 세미나\n발표일: 2026-09-22\n요약: 최신 논문의 핵심 기법을 소개합니다.',
                'attachments': [{'filename': '자료.pdf', 'url': 'unused', 'size': 13}]}

    def test_ingestion_nickname_date_sort_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / 'inbox'
            data = Path(tmp) / 'data'
            data.mkdir()
            with patch.multiple(website, INBOX_DIR=inbox, DATA_DIR=data, INDEX_PATH=data/'index.json', ITEMS_DIR=data/'items'):
                client = FakeClient()
                for mid, date, heading in [('123', '2026-09-21T01:00:00Z', '#세미나'),
                                           ('124', '2026-09-22T01:00:00Z', '# 세미나')]:
                    self.assertTrue(app.queue_message(client, '1', '2', self.message(mid, date, heading), inbox))
                    manifest = inbox / f'discord-2-{mid}.json'
                    website._process_inbox_manifest(manifest)
                    self.assertFalse(app.queue_message(client, '1', '2', self.message(mid, date, heading), inbox))
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
        invalid = ['', '아무 설명 없는 파일입니다.']
        for heading in ('# 세미나', '#세미나'):
            template = self.message(heading=heading)['content']
            invalid.extend([
                template.replace(heading, '#seminar'), template.replace(heading, '## 세미나'),
                template.replace(heading, '#  세미나'),
                template.replace('제목: 시계열 예측 세미나\n', ''),
                template.replace('시계열 예측 세미나', ''),
                template.replace('2026-09-22', '2026-02-30'),
                template.replace('2026-09-22', '2026-9-22'),
                template + '\n제목: 중복 제목', template + '\n알 수 없는 줄',
                template.replace('시계열 예측 세미나', '가' * 181),
                template.replace('최신 논문의 핵심 기법을 소개합니다.', '가' * 1001),
            ])
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
            client = FakeClient()
            for heading in ('# 세미나', '#세미나'):
                message = self.message(heading=heading)
                message['content'] = '\n  ' + message['content']
                message['attachments'] = []
                with self.subTest(heading=heading), self.assertRaisesRegex(website.IngestError, 'FORMAT_ATTACHMENT'):
                    app.queue_message(client, '1', '2', message, Path(tmp))
            for content in ('안녕하세요', '# 세미나 관련 질문입니다.', '#세미나 관련 질문입니다.'):
                message['content'] = content
                self.assertFalse(app.queue_message(client, '1', '2', message, Path(tmp)))
            self.assertEqual(client.requests, 0)
            self.assertEqual(client.downloads, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_template_allows_blank_lines_and_korean_colons_in_summary(self):
        for heading in ('# 세미나', '#세미나'):
            with self.subTest(heading=heading):
                fields = app.parse_seminar_message('\n' + heading + '\n\n제목: 한글 제목\n발표일: 2024-02-29\n요약: 방법: 시계열 예측\n')
                self.assertEqual(fields['title'], '한글 제목')
                self.assertEqual(fields['summary'], '방법: 시계열 예측')
                self.assertEqual(fields['presented_on'], '2024-02-29')

    def test_heading_errors_show_canonical_template(self):
        for content in (None, '', '#seminar\n제목: 제목'):
            with self.subTest(content=content), self.assertRaisesRegex(website.IngestError, '# 세미나'):
                app.parse_seminar_message(content)

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

    def test_file_only_upload_prompts_without_downloading_or_publishing(self):
        message = self.message()
        message['content'] = ''
        client, forms = FakeClient(), Mock()
        forms.offer.return_value = True
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(app.collect_message(client, '1', '2', message, forms, Path(tmp)), 'prompted')
            forms.offer.assert_called_once_with(message)
            self.assertEqual(client.downloads, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            message['content'] = self.message()['content'].replace('#세미나', '# 세미나')
            self.assertEqual(app.collect_message(client, '1', '2', message, forms, Path(tmp)), 'queued')
            self.assertEqual(forms.offer.call_count, 1)

    def test_modal_fields_are_validated_and_keep_original_upload_identity(self):
        message = self.message()
        message['content'] = ''
        fields = {'title': '한글 제목', 'presented_on': '2024-02-29', 'summary': '첫 줄\n둘째 줄'}
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            self.assertTrue(app.queue_message(client, '1', '2', message, inbox, fields=fields))
            saved = json.loads((inbox / 'discord-2-123.json').read_text())
            self.assertEqual(saved['title'], '한글 제목')
            self.assertEqual(saved['summary'], '첫 줄 둘째 줄')
            self.assertEqual(saved['uploaded_at'], message['timestamp'])
            self.assertEqual(saved['source_message_id'], 'discord:1:2:123')
            self.assertEqual(saved['presenter_discord'], '연구실 닉네임')
            self.assertEqual(saved['files'][0]['name'], '자료.pdf')
            message['id'] = '125'
            fields['presented_on'] = '2026-02-30'
            with self.assertRaises(website.IngestError):
                app.queue_message(client, '1', '2', message, inbox, fields=fields)
            self.assertFalse((inbox / 'discord-2-125.json').exists())
            self.assertEqual(client.downloads, 1)

    def test_invalid_attachment_metadata_before_any_network(self):
        for attachments in [[], [{'filename': 'a.pdf', 'size': 0}],
                            [{'filename': 'a.pdf', 'size': -1}],
                            [{'filename': 'a.pdf', 'size': '10'}],
                            [{'filename': 'a.pdf', 'size': app.MAX_FILE_BYTES + 1}],
                            [{'filename': 'a.pdf', 'size': 1}] * 11]:
            with self.subTest(attachments=attachments), tempfile.TemporaryDirectory() as tmp:
                client = FakeClient()
                message = self.message()
                message['attachments'] = attachments
                with self.assertRaises(website.IngestError):
                    app.queue_message(client, '1', '2', message, Path(tmp))
                self.assertEqual(client.requests, 0)

    def test_interaction_ack_uses_no_bot_auth_and_accepts_empty_204(self):
        client = app.Client('PRIVATE_BOT_TOKEN')
        with patch.object(client.opener, 'open', return_value=io.BytesIO(b'')) as request:
            self.assertIsNone(client.post('/interactions/1/PRIVATE_INTERACTION/callback',
                                         {'type': 5, 'data': {'flags': 64}},
                                         timeout=2.5, retries=1, authenticated=False))
            sent = request.call_args.args[0]
            self.assertNotIn('Authorization', dict(sent.header_items()))
            self.assertEqual(json.loads(sent.data)['type'], 5)
            self.assertEqual(request.call_args.kwargs['timeout'], 2.5)

    def test_ack_rate_limit_does_not_sleep_or_replay_dead_interaction(self):
        client = app.Client('PRIVATE_BOT_TOKEN')
        failure = urllib.error.HTTPError('https://discord.com/PRIVATE_INTERACTION', 429, 'rate limited', {}, io.BytesIO(b'{"retry_after":15}'))
        with patch.object(client.opener, 'open', side_effect=failure) as request, patch.object(app.time, 'sleep') as sleep:
            with self.assertRaises(app.ApiError) as caught:
                client.post('/interactions/1/PRIVATE_INTERACTION/callback', {'type': 9},
                            timeout=2.5, retries=1, authenticated=False)
            self.assertEqual(caught.exception.status, 429)
            self.assertNotIn('PRIVATE', str(caught.exception))
            request.assert_called_once()
            sleep.assert_not_called()

if __name__ == '__main__':
    unittest.main()
