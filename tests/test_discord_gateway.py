"""Offline protocol tests; no Discord token or network connection is needed."""
import json
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from discord_sync import gateway


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSocket:
    def __init__(self, frames=(), clock=None):
        self.frames = queue.Queue()
        for frame in frames:
            self.frames.put(frame)
        self.clock = clock
        self.sent = []
        self.closed = False
        self.timeout = None

    def send(self, data):
        self.sent.append(json.loads(data))

    def settimeout(self, value):
        self.timeout = value

    def recv_data_frame(self, control_frame=False):
        if self.closed:
            raise gateway.websocket.WebSocketConnectionClosedException()
        try:
            item = self.frames.get(timeout=0.01)
        except queue.Empty:
            if self.clock:
                self.clock.advance(self.timeout)
            raise gateway.websocket.WebSocketTimeoutException() from None
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        if isinstance(item, int):
            return gateway.websocket.ABNF.OPCODE_CLOSE, SimpleNamespace(data=item.to_bytes(2, "big"))
        return gateway.websocket.ABNF.OPCODE_TEXT, SimpleNamespace(data=json.dumps(item).encode())

    def abort(self):
        self.closed = True

    def shutdown(self):
        self.closed = True


HELLO = {"op": 10, "d": {"heartbeat_interval": 1000}}
READY = {"op": 0, "t": "READY", "s": 1, "d": {
    "session_id": "test-session", "resume_gateway_url": "wss://gateway-us-east1-b.discord.gg"}}


class GatewayTests(unittest.TestCase):
    def make_gateway(self, frames=(), **options):
        clock = Clock()
        connection = FakeSocket(frames, clock)
        factory = Mock(return_value=connection)
        client = gateway.Gateway("fake-secret-token", Mock(), socket_factory=factory,
                                 clock=clock, random_source=lambda: 0.5, **options)
        self.addCleanup(client.close)
        return client, connection, clock, factory

    def test_vendor_is_private_pinned_and_imports_without_pip(self):
        self.assertEqual(gateway.websocket.__version__, "1.9.2")
        self.assertEqual(gateway.websocket.__name__, "discord_sync.vendor.websocket")
        self.assertFalse(gateway.websocket.isEnabledForTrace())

    def test_identify_zero_intents_and_disables_redirects(self):
        client, connection, _, factory = self.make_gateway([HELLO, READY, {"op": 7}])
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        self.assertEqual(connection.sent[0]["op"], 2)
        self.assertEqual(connection.sent[0]["d"]["intents"], 0)
        self.assertTrue(client.ready.is_set())
        factory.assert_called_once_with(gateway.GATEWAY_URL, timeout=10,
                                        enable_multithread=True, suppress_origin=True, redirect_limit=0)

    def test_resume_uses_last_sequence_and_validated_regional_host(self):
        client, connection, _, factory = self.make_gateway([HELLO, READY,
            {"op": 0, "t": "OTHER_EVENT", "s": 31, "d": {}}, {"op": 7}])
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        client.ready.clear()
        client._disconnect()
        resumed = FakeSocket([HELLO, {"op": 0, "t": "RESUMED", "s": 32, "d": {}}, {"op": 7}])
        factory.return_value = resumed
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        self.assertEqual(factory.call_args.args[0], "wss://gateway-us-east1-b.discord.gg/?v=10&encoding=json")
        self.assertEqual(resumed.sent[0], {"op": 6, "d": {
            "token": "fake-secret-token", "session_id": "test-session", "seq": 31}})
        self.assertTrue(client.ready.is_set())
        self.assertEqual(client._sequence, 32)

    def test_server_heartbeat_responds_with_sequence_and_ack(self):
        client, connection, _, _ = self.make_gateway([HELLO, READY, {"op": 1}, {"op": 11}, {"op": 7}])
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        self.assertEqual(connection.sent[-1], {"op": 1, "d": 1})
        self.assertFalse(client._awaiting_ack)

    def test_missing_ack_disconnects_without_waiting_for_socket_failure(self):
        client, connection, clock, _ = self.make_gateway([HELLO, READY])
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        heartbeats = [item for item in connection.sent if item["op"] == 1]
        self.assertEqual(len(heartbeats), 1)
        self.assertGreaterEqual(clock.now, 101.5)
        self.assertTrue(client._can_resume())

    def test_requested_heartbeat_just_before_scheduled_one_has_full_ack_window(self):
        client, connection, clock, _ = self.make_gateway()
        client._socket = connection
        client._handle_payload(HELLO)
        clock.advance(0.49)
        client._handle_payload({"op": 1})
        self.assertAlmostEqual(client._ack_due, 101.49)
        clock.advance(0.01)
        client._heartbeat()
        self.assertAlmostEqual(client._ack_due, 101.49)

    def test_invalid_session_false_forgets_and_true_preserves_session(self):
        for resumable in (True, False):
            client, _, _, _ = self.make_gateway([HELLO, READY, {"op": 9, "d": resumable}])
            with self.assertRaises(gateway._Reconnect) as caught:
                client._run_connection()
            self.assertEqual(client._can_resume(), resumable)
            self.assertGreaterEqual(caught.exception.delay, 1)
            self.assertLessEqual(caught.exception.delay, 5)

    def test_fatal_codes_stop_and_diagnostics_never_expose_secrets(self):
        for code in (4004, 4010, 4011, 4012, 4013, 4014):
            client, _, _, _ = self.make_gateway([HELLO, code])
            with self.assertLogs(gateway.LOG, level="ERROR") as captured:
                client._run()
            self.assertEqual(client.failed, gateway._FATAL_CODES[code])
            self.assertFalse(client.ready.is_set())
            self.assertTrue(client._stop.is_set())
            self.assertNotIn("fake-secret-token", " ".join(captured.output))

    def test_invalid_seq_and_timeout_require_fresh_session(self):
        for code in (1000, 1001, 4003, 4007, 4009):
            client, _, _, _ = self.make_gateway([HELLO, READY, code])
            with self.assertRaises(gateway._Reconnect):
                client._run_connection()
            self.assertFalse(client._can_resume())
            self.assertIsNone(client.failed)

    def test_rate_limit_has_minimum_retry_delay(self):
        client, _, _, _ = self.make_gateway([HELLO, 4008])
        with self.assertRaises(gateway._Reconnect) as caught:
            client._run_connection()
        self.assertEqual(caught.exception.delay, 60)

    def test_untrusted_resume_urls_rejected_before_any_connection(self):
        invalid = [None, "ws://gateway.discord.gg", "wss://example.org",
                   "wss://gateway.discord.gg.evil.test", "wss://discord.gg",
                   "wss://user:secret@gateway.discord.gg", "wss://gateway.discord.gg:444",
                   "wss://gateway.discord.gg:bad", "wss://gateway.discord.gg/evil",
                   "wss://gateway.discord.gg?token=secret", "wss://gateway.discord.gg#other",
                   "wss://gateway.discord.gg\n", "wss://127.0.0.1"]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                gateway._resume_url(url)
        self.assertEqual(gateway._resume_url("wss://gateway.discord.gg:443/"), gateway.GATEWAY_URL)

    def test_bad_ready_url_never_stored_or_followed(self):
        ready = {**READY, "d": {**READY["d"], "resume_gateway_url": "wss://evil.test"}}
        client, connection, _, factory = self.make_gateway([HELLO, ready])
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        self.assertFalse(client._can_resume())
        self.assertFalse(client.ready.is_set())
        self.assertEqual(factory.call_count, 1)

    def test_slow_callback_does_not_block_heartbeat_or_second_interaction(self):
        client, connection, _, _ = self.make_gateway([HELLO, READY])
        entered = threading.Event()
        release = threading.Event()
        second = threading.Event()

        def callback(item):
            if item["id"] == "1":
                entered.set()
                release.wait(2)
            else:
                second.set()

        client._callback = callback
        client.start()
        self.assertTrue(client.ready.wait(1))
        connection.frames.put({"op": 0, "t": "INTERACTION_CREATE", "s": 2, "d": {"id": "1"}})
        self.assertTrue(entered.wait(1))
        connection.frames.put({"op": 1})
        connection.frames.put({"op": 11})
        connection.frames.put({"op": 0, "t": "INTERACTION_CREATE", "s": 3, "d": {"id": "2"}})
        try:
            self.assertTrue(second.wait(1))
            self.assertIn({"op": 1, "d": 2}, connection.sent)
        finally:
            release.set()
        client.close()
        self.assertFalse(client.ready.is_set())
        self.assertTrue(connection.closed)

    def test_worker_queue_is_bounded_and_only_interactions_dispatch(self):
        client, _, _, _ = self.make_gateway(queue_size=1)
        client._handle_payload({"op": 0, "t": "MESSAGE_CREATE", "d": {"token": "not-for-worker"}})
        self.assertTrue(client._jobs.empty())
        item = {"op": 0, "t": "INTERACTION_CREATE", "d": {"token": "temporary-secret"}}
        client._handle_payload(item)
        with self.assertLogs(gateway.LOG, level="WARNING") as captured:
            client._handle_payload(item)
        self.assertEqual(client._jobs.qsize(), 1)
        self.assertNotIn("temporary-secret", " ".join(captured.output))

    def test_expired_jobs_and_callback_exception_do_not_leak_payloads(self):
        client, _, clock, _ = self.make_gateway()
        client._jobs.put((clock() - 2, {"token": "temporary-secret"}))
        client._jobs.put((clock(), {"token": "temporary-secret"}))

        def failing_callback(item):
            client._stop.set()
            raise ValueError(item["token"])

        client._callback = failing_callback
        with self.assertLogs(gateway.LOG, level="WARNING") as captured:
            client._work()
        self.assertEqual(len(captured.output), 2)
        self.assertNotIn("temporary-secret", " ".join(captured.output))

    def test_retry_backoff_grows_and_network_error_text_is_private(self):
        client, _, _, _ = self.make_gateway()
        client._random = lambda: 0
        attempts = []

        def disconnect():
            attempts.append(True)
            if len(attempts) >= 4:
                client._stop.set()
            raise RuntimeError("fake-secret-token")

        with patch.object(client, "_run_connection", side_effect=disconnect), \
                patch.object(client._stop, "wait", return_value=False) as waiting, \
                self.assertLogs(gateway.LOG, level="WARNING") as captured:
            client._run()
        delays = [call.args[0] for call in waiting.call_args_list if call.args[0] > 0]
        self.assertEqual(delays, [0.5, 1, 2])
        self.assertNotIn("fake-secret-token", " ".join(captured.output))

    def test_identify_cooldown_and_daily_budget(self):
        client, _, clock, _ = self.make_gateway()
        client._identified_at = clock()
        self.assertEqual(client._identify_delay(), 5)
        clock.advance(3)
        self.assertEqual(client._identify_delay(), 2)
        client._identify_times.extend([clock()] * 900)
        self.assertEqual(client._identify_delay(), 86400)
        clock.advance(86401)
        self.assertEqual(client._identify_delay(), 0)

    def test_missing_hello_and_invalid_heartbeat_cannot_hang_connection(self):
        client, _, _, _ = self.make_gateway()
        with self.assertRaises(gateway._Reconnect):
            client._run_connection()
        for interval in (0, -1, True, "1000", float("nan"), float("inf")):
            with self.subTest(interval=interval), self.assertRaises(gateway._Reconnect):
                client._handle_payload({"op": 10, "d": {"heartbeat_interval": interval}})

    def test_empty_token_fails_without_network_and_start_is_idempotent(self):
        client, _, _, factory = self.make_gateway()
        client._token = ""
        with self.assertLogs(gateway.LOG, level="ERROR"):
            self.assertIs(client.start(), client)
        client.start()
        self.assertIsNotNone(client.failed)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
