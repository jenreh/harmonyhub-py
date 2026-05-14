"""Async WebSocket transport against the Harmony Hub port 8088 endpoint.

The hub speaks a request/response protocol over a single WebSocket. Each
request carries a UUID; replies that carry the same ``id`` are routed back to
the awaiting caller. Messages without an ``id`` are spontaneous events
(activity changes, state-digest updates) and are pushed onto an async queue
that callers can iterate.

The hub drops idle connections after ~60 seconds, so the transport sends a
ping every ``keepalive_interval_s`` (default 50s) and reconnects with
exponential backoff on disconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import websockets
from websockets.asyncio.client import ClientConnection

from harmonyhub.exceptions import HubUnavailableError, ProtocolError
from harmonyhub.models import HubEvent
from harmonyhub.protocol.http import HUB_ORIGIN, ProvisionInfo

_LOG = logging.getLogger(__name__)

_HUB_PORT = 8088
_HUB_CLOSE_AFTER_S = 60
_REQUEST_TIMEOUT_S = 10.0


def _ws_url(host: str, info: ProvisionInfo) -> str:
    domain = _domain_host(info.discovery_server) or "svcs.myharmony.com"
    return f"ws://{host}:{_HUB_PORT}/?domain={domain}&hubId={info.remote_id}"


def _domain_host(discovery_server: str | None) -> str | None:
    """Extract bare host from a discoveryServer field.

    The hub returns ``discoveryServer`` as a full URL (e.g.
    ``https://svcs.myharmony.com/Discovery/Discovery.svc``) but the WebSocket
    handshake's ``domain=`` parameter must be the host alone — otherwise the
    hub rejects the upgrade with HTTP 401.
    """
    if not discovery_server:
        return None
    parsed = urlparse(discovery_server)
    return parsed.hostname or discovery_server


def _envelope(
    remote_id: str, cmd: str, params: dict[str, Any] | None, msg_id: str
) -> dict:
    return {
        "hubId": remote_id,
        "timeout": 30,
        "hbus": {
            "cmd": cmd,
            "id": msg_id,
            "params": params or {"verb": "get", "format": "json"},
        },
    }


class WebSocketTransport:
    """Single-connection WebSocket transport with correlation and events."""

    def __init__(
        self,
        host: str,
        info: ProvisionInfo,
        *,
        keepalive_interval_s: float = 50.0,
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
        persistent: bool = False,
    ) -> None:
        self._host = host
        self._info = info
        self._keepalive = keepalive_interval_s
        self._request_timeout = request_timeout_s
        self._persistent = persistent

        self._ws: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._closed = False

        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._events: asyncio.Queue[HubEvent] = asyncio.Queue()
        self._connected_event = asyncio.Event()
        self._connect_error: BaseException | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._connected_event.is_set()

    async def connect(self) -> None:
        if self._ws is not None:
            return
        self._closed = False
        if self._persistent:
            self._supervisor_task = asyncio.create_task(
                self._supervisor(), name="harmony-ws-supervisor"
            )
            await self._connected_event.wait()
            if self._connect_error is not None:
                err = self._connect_error
                await self.close()
                raise err
        else:
            await self._open_once()

    async def close(self) -> None:
        self._closed = True
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor_task
            self._supervisor_task = None
        await self._teardown(reason="close()")

    async def notify(self, cmd: str, params: dict[str, Any] | None = None) -> None:
        """Send a fire-and-forget command without awaiting a correlated reply.

        Used for commands that the hub does not ack on the wire (notably
        ``holdAction`` press/release). Any side-effects surface via
        spontaneous events on the events queue.
        """
        if self._ws is None or not self._connected_event.is_set():
            raise HubUnavailableError("WebSocket not connected")
        envelope = _envelope(self._info.remote_id, cmd, params, uuid.uuid4().hex)
        await self._ws.send(json.dumps(envelope))

    async def request(
        self,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        """Send a request and return the matching response payload.

        Raises:
            HubUnavailableError: if the socket is not connected.
            ProtocolError: if no response arrives within the timeout.
        """
        if self._ws is None or not self._connected_event.is_set():
            raise HubUnavailableError("WebSocket not connected")
        msg_id = uuid.uuid4().hex
        envelope = _envelope(self._info.remote_id, cmd, params, msg_id)
        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        try:
            await self._ws.send(json.dumps(envelope))
            return await asyncio.wait_for(
                future, timeout=timeout or self._request_timeout
            )
        except TimeoutError as exc:
            actual_timeout = timeout or self._request_timeout
            raise ProtocolError(
                f"Request {cmd!r} timed out after {actual_timeout}s"
            ) from exc
        finally:
            self._pending.pop(msg_id, None)

    async def events(self) -> AsyncIterator[HubEvent]:
        """Yield spontaneous events as they arrive. Iteration ends on close()."""
        while not self._closed:
            try:
                event = await self._events.get()
            except asyncio.CancelledError:
                break
            yield event

    async def _open_once(self) -> None:
        url = _ws_url(self._host, self._info)
        _LOG.debug("Opening WebSocket to %s", url)
        try:
            self._ws = await websockets.connect(
                url,
                origin=HUB_ORIGIN,
                ping_interval=self._keepalive,
                ping_timeout=self._keepalive,
                close_timeout=5.0,
                max_size=4 * 1024 * 1024,
            )
        except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as exc:
            raise HubUnavailableError(f"WebSocket connect failed: {exc}") from exc
        self._reader_task = asyncio.create_task(
            self._reader(), name="harmony-ws-reader"
        )
        self._connected_event.set()

    async def _teardown(self, *, reason: str) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        self._connected_event.clear()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(HubUnavailableError(f"WebSocket closed: {reason}"))
        self._pending.clear()

    async def _supervisor(self) -> None:
        """Persistent-mode reconnect loop with exponential backoff."""
        backoff = 1.0
        while not self._closed:
            try:
                await self._open_once()
                self._connect_error = None
                backoff = 1.0
                if self._reader_task is not None:
                    await self._reader_task
            except HubUnavailableError as exc:
                _LOG.warning(
                    "WebSocket connect failed: %s — retry in %.1fs", exc, backoff
                )
                self._connect_error = exc
                self._connected_event.set()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOG.exception("WebSocket reader crashed; reconnecting")
            await self._teardown(reason="supervisor restart")
            if self._closed:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                self._dispatch(
                    raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                )
        except websockets.ConnectionClosed as exc:
            _LOG.info("WebSocket closed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOG.exception("WebSocket reader error")

    def _dispatch(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            _LOG.warning("Discarding non-JSON frame: %r", raw[:200])
            return
        if not isinstance(msg, dict):
            _LOG.warning("Discarding non-object frame: %r", msg)
            return
        msg_id = msg.get("id")
        if msg_id and msg_id in self._pending:
            fut = self._pending[msg_id]
            if not fut.done():
                fut.set_result(msg)
            return
        event = HubEvent(
            type=str(msg.get("type", "")), data=msg.get("data") or {}, raw=msg
        )
        self._events.put_nowait(event)
