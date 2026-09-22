# Bundled WebSocket transport

`websocket/` contains the unmodified runtime modules and `py.typed` from
**websocket-client 1.9.2**, distributed under Apache-2.0. The upstream CLI
`_wsdump.py`, tests, and wheel installation metadata are omitted. All included
copyright notices are retained; see `LICENSE.websocket-client`.

- Official release metadata: https://pypi.org/pypi/websocket-client/1.9.2/json
- Project: https://github.com/websocket-client/websocket-client
- Wheel: `websocket_client-1.9.2-py3-none-any.whl`
- SHA-256: `e1a673830a9c7bfa47b1cd3d5e4178f4c9651d80a4eab02c9c23a1c3ec6250ce`
- Retrieved and checksum verified: 2026-09-22

Import through `discord_sync.vendor.websocket`; no `sys.path` manipulation,
pip install, native extension, or Docker is required. Optional SOCKS proxy and
accelerator dependencies are not bundled. TLS verification remains enabled.
Do not enable frame tracing: Identify frames include the bot token, and
interaction payloads include temporary response credentials.

The separate `discord_sync.gateway.Gateway` implements Discord API v10 JSON
heartbeat, resume, reconnect and a bounded interaction worker pool. It requests
`intents: 0` because `INTERACTION_CREATE` is not gated by a Gateway intent.
The existing REST collector still requires its configured Message Content
Intent to read uploaded files. No Gateway state is persisted to disk.

References:
- https://docs.discord.com/developers/events/gateway#list-of-intents
- https://docs.discord.com/developers/events/gateway#sending-heartbeats
- https://docs.discord.com/developers/events/gateway#resuming
- https://docs.discord.com/developers/topics/opcodes-and-status-codes#gateway
- https://docs.discord.com/developers/interactions/receiving-and-responding
