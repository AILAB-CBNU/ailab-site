"""Discord interaction-only Gateway, including its offline WebSocket dependency.

REST polling still collects attachments. The callback must acknowledge each
interaction via REST within Discord's three-second window and hand longer work
to its own job queue. It runs outside the socket/heartbeat thread. No tokens,
frames, remote close reasons or exception bodies are ever written to logs.
"""
from __future__ import annotations

from collections import deque
import json
import logging
import math
import queue
import random
import re
import sys
import threading
import time
from urllib.parse import urlsplit

from .vendor import websocket

LOG = logging.getLogger("discord-sync.gateway")
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
_FATAL_CODES = {
    4004: "Discord bot token was rejected. Update the bot token and restart the collector.",
    4010: "Discord rejected the Gateway shard configuration. Update the collector.",
    4011: "Discord requires sharding for this bot. Contact the bot administrator.",
    4012: "Discord rejected the Gateway API version. Update the collector.",
    4013: "Discord rejected the Gateway intents. Update the collector.",
    4014: "Discord disallowed the Gateway intents. Check the bot settings and restart.",
}


def _resume_url(value):
    """Restrict any token-bearing connection to Discord's TLS Gateway hosts."""
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise ValueError("Invalid Gateway URL")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "wss" or not re.fullmatch(
                r"gateway(?:-[a-z0-9-]+)?\.discord\.gg", parsed.hostname or "")
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("Invalid Gateway URL")
    except ValueError:
        raise ValueError("Invalid Gateway URL") from None
    return f"wss://{parsed.hostname}/?v=10&encoding=json"


class _Reconnect(Exception):
    def __init__(self, delay=0):
        self.delay = delay


class Gateway:
    """Background Gateway with ``ready`` Event and a safe ``failed`` message.

    ``start()`` is idempotent; ``close()`` permanently stops this instance.
    Callbacks run on at most four daemon workers with a queue of eight items.
    Excess or expired interactions are dropped with a fixed warning; the user
    can click the button again. Authentication failures stop automatic retries.
    The injectable socket factory/clock/random source support offline tests.
    """

    def __init__(self, token, on_interaction, *, socket_factory=None,
                 clock=None, random_source=None, workers=4, queue_size=8):
        if not callable(on_interaction):
            raise TypeError("on_interaction must be callable")
        if not 1 <= workers <= 16 or not 1 <= queue_size <= 64:
            raise ValueError("Invalid Gateway worker limits")
        self._token = token
        self._callback = on_interaction
        self._factory = socket_factory or websocket.create_connection
        self._clock = clock or time.monotonic
        self._random = random_source or random.random
        self._worker_count = workers
        self._jobs = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._socket_lock = threading.Lock()
        self._socket = None
        self._thread = None
        self._workers = []
        self._failed = None
        self.ready = threading.Event()
        self._session_id = None
        self._sequence = None
        self._resume_gateway_url = None
        self._identify_times = deque()
        self._identified_at = None
        self._ready_at = None
        self._heartbeat_interval = None
        self._heartbeat_due = None
        self._awaiting_ack = False
        self._ack_due = None

    @property
    def failed(self):
        return self._failed

    def start(self):
        with self._lifecycle_lock:
            if self._thread is not None or self._stop.is_set():
                return self
            if not isinstance(self._token, str) or not self._token.strip():
                self._fail(_FATAL_CODES[4004])
                return self
            # The private library must never trace Identify or interaction data.
            websocket.enableTrace(False)
            for number in range(self._worker_count):
                worker = threading.Thread(target=self._work, daemon=True,
                                          name=f"discord-interaction-{number}")
                worker.start()
                self._workers.append(worker)
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="discord-gateway")
            self._thread.start()
        return self

    def close(self):
        self._stop.set()
        self.ready.clear()
        self._disconnect()
        current = threading.current_thread()
        # Bound shutdown even when a callback is still doing a REST request.
        deadline = time.monotonic() + 2
        for thread in [self._thread, *self._workers]:
            if thread is not None and thread is not current:
                thread.join(max(0, deadline - time.monotonic()))
        self._discard_jobs()

    def _fail(self, message):
        self._failed = message
        self.ready.clear()
        self._stop.set()
        LOG.error("%s", message)

    def _forget_session(self):
        self._session_id = self._sequence = self._resume_gateway_url = None

    def _can_resume(self):
        return (self._session_id is not None and self._sequence is not None
                and self._resume_gateway_url is not None)

    def _disconnect(self):
        with self._socket_lock:
            connection, self._socket = self._socket, None
        if connection is not None:
            # Closing TCP preserves the session; sending close 1000/1001 does not.
            for method in ("abort", "shutdown"):
                try:
                    getattr(connection, method)()
                except Exception:
                    pass

    def _send(self, op, data):
        if self._socket is None:
            raise _Reconnect()
        self._socket.send(json.dumps({"op": op, "d": data}, separators=(",", ":")))

    def _heartbeat(self):
        self._send(1, self._sequence)
        if not self._awaiting_ack and self._heartbeat_interval is not None:
            self._ack_due = self._clock() + self._heartbeat_interval
        self._awaiting_ack = True

    def _handle_payload(self, payload):
        if not isinstance(payload, dict):
            raise _Reconnect()
        op, data = payload.get("op"), payload.get("d")
        sequence = payload.get("s")
        if op == 0 and isinstance(sequence, int) and not isinstance(sequence, bool):
            self._sequence = sequence
        if op == 10:
            if self._heartbeat_interval is not None or not isinstance(data, dict):
                raise _Reconnect()
            interval = data.get("heartbeat_interval")
            if (isinstance(interval, bool) or not isinstance(interval, (int, float))
                    or not math.isfinite(interval) or not 1000 <= interval <= 300000):
                raise _Reconnect()
            self._heartbeat_interval = interval / 1000
            self._heartbeat_due = self._clock() + self._heartbeat_interval * self._random()
            if self._can_resume():
                self._send(6, {"token": self._token, "session_id": self._session_id,
                               "seq": self._sequence})
            else:
                self._identify_times.append(self._clock())
                self._identified_at = self._clock()
                self._send(2, {"token": self._token, "intents": 0, "properties": {
                    "os": sys.platform, "browser": "ailab-seminar", "device": "ailab-seminar"}})
        elif op == 11:
            self._awaiting_ack = False
        elif op == 1:
            self._heartbeat()
        elif op == 7:
            raise _Reconnect()
        elif op == 9:
            if data is not True:
                self._forget_session()
            raise _Reconnect(1 + 4 * self._random())
        elif op == 0 and payload.get("t") == "READY":
            if not isinstance(data, dict) or not isinstance(data.get("session_id"), str):
                raise _Reconnect()
            try:
                url = _resume_url(data.get("resume_gateway_url"))
            except ValueError:
                self._forget_session()
                raise _Reconnect() from None
            if not data["session_id"] or self._sequence is None:
                raise _Reconnect()
            self._session_id = data["session_id"]
            self._resume_gateway_url = url
            self._mark_ready()
        elif op == 0 and payload.get("t") == "RESUMED":
            self._mark_ready()
        elif op == 0 and payload.get("t") == "INTERACTION_CREATE" and isinstance(data, dict):
            try:
                self._jobs.put_nowait((self._clock(), data))
            except queue.Full:
                LOG.warning("Discord interaction queue is busy; click the button again.")

    def _mark_ready(self):
        self._ready_at = self._clock()
        self.ready.set()
        LOG.info("Discord interaction Gateway ready.")

    def _handle_close(self, data):
        code = int.from_bytes(data[:2], "big") if isinstance(data, bytes) and len(data) >= 2 else None
        if code in _FATAL_CODES:
            self._fail(_FATAL_CODES[code])
        elif code in (1000, 1001, 4003, 4007, 4009):
            self._forget_session()
        raise _Reconnect(60 if code == 4008 else 0)

    def _run_connection(self):
        self._heartbeat_interval = self._heartbeat_due = None
        self._awaiting_ack = False
        self._ack_due = None
        self._ready_at = None
        url = self._resume_gateway_url if self._can_resume() else GATEWAY_URL
        # Resume URLs were validated from READY. Never follow a redirect to a
        # different host or downgrade TLS before sending a bot credential.
        connection = self._factory(url, timeout=10, enable_multithread=True,
                                   suppress_origin=True, redirect_limit=0)
        with self._socket_lock:
            self._socket = connection
        connection.settimeout(0.5)
        connected_at = self._clock()
        while not self._stop.is_set():
            now = self._clock()
            if self._awaiting_ack and self._ack_due is not None and now >= self._ack_due:
                raise _Reconnect()
            if self._heartbeat_due is not None and now >= self._heartbeat_due:
                self._heartbeat()
                self._heartbeat_due = now + self._heartbeat_interval
            if not self.ready.is_set() and now - connected_at > 30:
                raise _Reconnect()
            try:
                opcode, frame = connection.recv_data_frame(control_frame=True)
            except websocket.WebSocketTimeoutException:
                continue
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                self._handle_close(frame.data)
            elif opcode == websocket.ABNF.OPCODE_TEXT:
                # No binary or stream compression is negotiated.
                if len(frame.data) > 1024 * 1024:
                    raise _Reconnect()
                self._handle_payload(json.loads(frame.data))

    def _identify_delay(self):
        now = self._clock()
        while self._identify_times and now - self._identify_times[0] >= 86400:
            self._identify_times.popleft()
        # Single-bot process: avoid hitting Discord's 1000/day reset limit,
        # including rapid reconnects that never reach READY.
        if len(self._identify_times) >= 900:
            return max(0, self._identify_times[0] + 86400 - now)
        return max(0, 5 - (now - self._identified_at)) if self._identified_at is not None else 0

    def _run(self):
        failures = 0
        try:
            while not self._stop.is_set():
                if not self._can_resume() and self._stop.wait(self._identify_delay()):
                    break
                minimum_delay = 0
                try:
                    self._run_connection()
                except _Reconnect as exc:
                    minimum_delay = exc.delay
                except Exception:
                    # Network exceptions may contain tokens, URLs or proxies.
                    # Never interpolate their type, text or traceback here.
                    pass
                finally:
                    self.ready.clear()
                    self._disconnect()
                if self._stop.is_set():
                    break
                if self._ready_at is not None and self._clock() - self._ready_at >= 60:
                    failures = 0
                delay = max(minimum_delay, min(60, 2 ** min(failures, 6)) * (0.5 + self._random() / 2))
                failures += 1
                LOG.warning("Discord interaction Gateway disconnected; reconnecting.")
                if self._stop.wait(delay):
                    break
        finally:
            self.ready.clear()
            self._disconnect()

    def _work(self):
        while not self._stop.is_set():
            try:
                received_at, interaction = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self._stop.is_set():
                    continue
                if self._clock() - received_at > 1.5:
                    LOG.warning("Discord interaction expired in queue; click the button again.")
                    continue
                self._callback(interaction)
            except Exception:
                LOG.warning("Discord interaction failed; click the button again.")
            finally:
                self._jobs.task_done()

    def _discard_jobs(self):
        while True:
            try:
                self._jobs.get_nowait()
                self._jobs.task_done()
            except queue.Empty:
                return
