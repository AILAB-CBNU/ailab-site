import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from discord_sync import app
from discord_sync.briefing import Briefings, KST, collect_day, validate_extraction, chunks


def extraction():
    return {"summary": [{"text": "다음 세미나 논의", "source_id": "100"}], "questions": [],
            "items": [{"title": "실험 정리", "owner_id": "200", "due": "2026-09-24", "time_note": "",
                       "source_id": "100", "quote": "제가 실험 정리", "kind": "personal"}], "updates": []}


MESSAGES = [{"id": "100", "author_id": "200", "mentions": [], "name": "연구원",
             "timestamp": "2026-09-22T08:00:00Z", "content": "제가 실험 정리하겠습니다."}]


class Client:
    def __init__(self):
        self.posts, self.messages = [], {}
        self.block = False
        self.uncertain = False

    def get(self, route):
        if route == "/users/@me":
            return {"id": "999"}
        if "/members/" in route:
            return {"user": {"id": route.rsplit("/", 1)[-1]}}
        if "/messages?" in route:
            return list(self.messages.values())
        return {"id": route.rsplit("/", 1)[-1], "guild_id": "1", "type": 0}

    def post(self, route, payload, **options):
        if route == "/users/@me/channels":
            return {"id": "500"}
        if self.block and route == "/channels/500/messages":
            raise app.ApiError(403)
        self.posts.append((route, copy.deepcopy(payload)))
        if route.startswith("/interactions/"):
            return
        mid = str(1000 + len(self.posts))
        message = dict(payload, id=mid, author={"id": "999"})
        self.messages[mid] = message
        if self.uncertain:
            self.uncertain = False
            raise TimeoutError()
        return message


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Client()
        self.config = {"source": "2", "destination": "3", "start_date": "2026-09-22"}
        self.calls = 0
        def model(messages, tasks):
            self.calls += 1
            return extraction()
        self.bot = Briefings(self.client, "1", self.config, self.temp.name, model)

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        with patch('discord_sync.briefing.collect_day', return_value=MESSAGES):
            self.bot.prepare(date(2026, 9, 22))

    def interaction(self, custom, owner="200", **changes):
        event = {"type": 3, "id": "900", "token": "fake-interaction", "guild_id": "1", "channel_id": "3",
                 "data": {"custom_id": custom}, "member": {"user": {"id": owner}, "permissions": "0"}}
        event.update(changes)
        self.bot.handle(event)
        return self.client.posts[-1][1]["data"]

    def test_evidence_and_assignees_fail_closed(self):
        self.assertEqual(len(validate_extraction(extraction(), MESSAGES, {})['items']), 1)
        for field, value in [('owner_id', '300'), ('source_id', '404'), ('quote', 'invented'), ('due', '2026-02-30')]:
            result = extraction()
            result['items'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_extraction(result, MESSAGES, {})

    def test_personal_details_only_in_dm_and_own_private_view(self):
        self.prepare()
        self.bot.deliver(date(2026, 9, 22))
        public = [p for route, p in self.client.posts if route == '/channels/3/messages']
        private = [p for route, p in self.client.posts if route == '/channels/500/messages']
        self.assertTrue(public and private)
        self.assertNotIn('실험 정리', ''.join(p['content'] for p in public))
        self.assertIn('실험 정리', private[0]['content'])
        data = self.interaction('brief:mine:0')
        self.assertEqual(data['flags'], 64)
        self.assertIn('실험 정리', data['content'])
        self.assertNotIn('실험 정리', self.interaction('brief:mine:0', owner='300')['content'])

    def test_only_owner_can_complete_and_completion_persists(self):
        self.prepare()
        task_id = next(iter(self.bot.state['tasks']))
        self.interaction('brief:done:' + task_id, owner='300')
        self.assertEqual(self.bot.state['tasks'][task_id]['status'], 'open')
        self.interaction('brief:done:' + task_id)
        self.assertEqual(self.bot.state['tasks'][task_id]['status'], 'done')
        reload = Briefings(self.client, '1', self.config, self.temp.name)
        self.assertEqual(reload.state['tasks'][task_id]['status'], 'done')

    def test_wrong_guild_or_channel_never_exposes_personal_tasks(self):
        self.prepare()
        for change in ({'guild_id': 'other'}, {'channel_id': 'other'}, {'guild_id': None, 'channel_id': 'unknown'}):
            self.assertNotIn('실험 정리', self.interaction('brief:mine:0', **change)['content'])

    def test_dm_block_does_not_publish_personal_details_elsewhere(self):
        self.prepare()
        self.client.block = True
        self.bot.deliver(date(2026, 9, 22))
        record = self.bot.state['days']['2026-09-22']
        self.assertTrue(record['complete'])
        self.assertTrue(record['deliveries'][1]['blocked'])
        self.assertNotIn('실험 정리', ''.join(p['content'] for _, p in self.client.posts))

    def test_restart_and_timeout_do_not_duplicate_public_post(self):
        self.prepare()
        self.client.uncertain = True
        with self.assertRaises(TimeoutError):
            self.bot.deliver(date(2026, 9, 22))
        reload = Briefings(self.client, '1', self.config, self.temp.name)
        reload.deliver(date(2026, 9, 22))
        self.assertEqual(len([r for r, _ in self.client.posts if r == '/channels/3/messages']), 1)
        reload.deliver(date(2026, 9, 22))
        self.assertEqual(len([r for r, _ in self.client.posts if r == '/channels/500/messages']), 1)

    def test_unresolved_delivery_is_not_blindly_replayed(self):
        self.prepare()
        self.bot.state['days']['2026-09-22']['deliveries'][0].update(channel='3', inflight='0')
        with self.assertRaisesRegex(RuntimeError, 'Uncertain'):
            self.bot.deliver(date(2026, 9, 22))
        self.assertEqual(self.client.posts, [])

    def test_kst_schedule_runs_once_and_first_day_is_respected(self):
        with patch('discord_sync.briefing.collect_day', return_value=MESSAGES):
            self.bot.tick(datetime(2026, 9, 23, 8, 59, tzinfo=KST))
            self.assertEqual(self.calls, 0)
            self.bot.tick(datetime(2026, 9, 23, 9, tzinfo=KST))
            self.bot.tick(datetime(2026, 9, 23, 12, tzinfo=KST))
            self.assertEqual(self.calls, 1)
        reload = Briefings(self.client, '1', self.config, self.temp.name)
        reload.tick(datetime(2026, 9, 23, 13, tzinfo=KST))
        self.assertEqual(len([r for r, _ in self.client.posts if r == '/channels/3/messages']), 1)

    def test_retry_budget_survives_restart(self):
        with patch('discord_sync.briefing.collect_day', side_effect=RuntimeError('failure')):
            for hour in (9, 10, 11):
                with self.assertRaises(RuntimeError):
                    self.bot.tick(datetime(2026, 9, 23, hour, tzinfo=KST))
            reload = Briefings(self.client, '1', self.config, self.temp.name)
            reload.tick(datetime(2026, 9, 23, 12, tzinfo=KST))
            self.assertEqual(reload.state['attempts']['2026-09-22']['count'], 3)

    def test_collection_boundaries_bot_exclusion_and_secret_redaction(self):
        day = date(2026, 9, 22)
        start = datetime(2026, 9, 22, tzinfo=KST)
        def msg(at, content, bot=False):
            return {'id': str((int(at.timestamp()*1000)-1420070400000)<<22), 'content':content,
                    'timestamp':at.isoformat(), 'author':{'id':'200','bot':bot}, 'mentions':[]}
        page = [msg(start+timedelta(hours=23), 'valid sk-'+('x'*40)), msg(start, 'midnight'),
                msg(start+timedelta(hours=1), 'bot', True), msg(start-timedelta(seconds=1), 'old')]
        with patch.object(self.client, 'get', return_value=page):
            result = collect_day(self.client, '2', day)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['content'], 'midnight')
        self.assertNotIn('sk-', result[1]['content'])

    def test_chunks_and_mentions_are_bounded(self):
        self.assertTrue(all(len(p) <= 1700 for p in chunks(['x'*5000, '한글'*3000])))
        self.assertTrue(all(len(p.encode('utf-16-le'))//2 <= 1700 for p in chunks(['☀️🧑‍💻'*1000])))
        self.prepare()
        self.bot.deliver(date(2026, 9, 22))
        self.assertTrue(all(p['allowed_mentions']['parse'] == [] for _, p in self.client.posts))

    def test_changed_channel_audience_stops_before_collection_or_sending(self):
        self.bot.config['audience_signature'] = 'old-permissions'
        with self.assertRaisesRegex(RuntimeError, 'permissions changed'):
            self.bot.tick(datetime(2026, 9, 23, 9, tzinfo=KST))
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.client.posts, [])
