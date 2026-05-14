"""In-process fake Harmony Hub for tests.

Runs only the WebSocket endpoint. The HTTP provisioning POST is mocked via
``pytest-httpx`` in unit tests (or via ``fetch_provision_info`` monkey-patch),
because adding a full HTTP server here would drag in an extra dependency that
is unrelated to the protocol the library exercises in production.

Records ``holdAction`` and ``changeChannel`` params for assertions.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

from harmonyhub.protocol.http import ProvisionInfo

_LOG = logging.getLogger(__name__)


@dataclass
class FakeState:
    config: dict[str, Any] = field(default_factory=dict)
    current_activity: str = "-1"
    received_commands: list[dict[str, Any]] = field(default_factory=list)


def _default_config() -> dict[str, Any]:
    def _action(cmd: str, dev: str) -> str:
        return json.dumps(
            {"command": cmd, "type": "IRCommand", "deviceId": dev},
            separators=(",", ":"),
        )

    return {
        "configVersion": 7,
        "activity": [
            {"id": "-1", "label": "PowerOff"},
            {"id": "100", "label": "Watch TV"},
            {"id": "200", "label": "Apple TV"},
        ],
        "device": [
            {
                "id": "1001",
                "label": "Denon AVR",
                "manufacturer": "Denon",
                "model": "X1700",
                "controlGroup": [
                    {
                        "name": "Volume",
                        "function": [
                            {
                                "name": "VolumeUp",
                                "label": "Volume Up",
                                "action": _action("VolumeUp", "1001"),
                            },
                            {
                                "name": "VolumeDown",
                                "label": "Volume Down",
                                "action": _action("VolumeDown", "1001"),
                            },
                            {
                                "name": "Mute",
                                "label": "Mute",
                                "action": _action("Mute", "1001"),
                            },
                        ],
                    },
                    {
                        "name": "Power",
                        "function": [
                            {
                                "name": "PowerOn",
                                "label": "Power On",
                                "action": _action("PowerOn", "1001"),
                            },
                            {
                                "name": "PowerOff",
                                "label": "Power Off",
                                "action": _action("PowerOff", "1001"),
                            },
                        ],
                    },
                ],
            },
            {
                "id": "1002",
                "label": "Vodafone Receiver",
                "manufacturer": "Vodafone",
                "model": "GigaTV",
                "controlGroup": [
                    {
                        "name": "Numeric",
                        # IR command for Number<N> is the bare digit per typical hub configs.
                        "function": [
                            {
                                "name": f"Number{i}",
                                "label": str(i),
                                "action": _action(str(i), "1002"),
                            }
                            for i in range(10)
                        ],
                    },
                    {
                        "name": "Channel",
                        "function": [
                            {
                                "name": "ChannelUp",
                                "label": "Channel Up",
                                "action": _action("ChannelUp", "1002"),
                            },
                            {
                                "name": "ChannelDown",
                                "label": "Channel Down",
                                "action": _action("ChannelDown", "1002"),
                            },
                            {
                                "name": "Enter",
                                "label": "OK",
                                "action": _action("Enter", "1002"),
                            },
                        ],
                    },
                ],
            },
        ],
    }


class FakeHub:
    """In-process fake hub. Use as an async context manager."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        self.ws_port = 0
        self.state = FakeState(config=_default_config())
        self._ws_server: Any = None

    async def __aenter__(self) -> FakeHub:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    @property
    def provision_info(self) -> ProvisionInfo:
        """Synthetic provisioning info matching what the real hub would return."""
        return ProvisionInfo(
            remote_id="9999",
            discovery_server="svcs.myharmony.com",
            account_id="test-account",
            email_redacted="te***@example.com",
            raw={"friendlyName": "FakeHub", "currentFwVersion": "9.9.9"},
        )

    async def start(self) -> None:
        self._ws_server = await websockets.serve(self._ws_handler, self.host, 0)
        for sock in self._ws_server.sockets or []:
            self.ws_port = sock.getsockname()[1]
            break

    async def stop(self) -> None:
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()
            self._ws_server = None

    async def _ws_handler(self, connection: Any) -> None:
        async for raw in connection:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            hbus = msg.get("hbus") or {}
            msg_id = hbus.get("id")
            cmd = hbus.get("cmd")
            params = hbus.get("params") or {}
            reply = self._handle_command(cmd, params)
            payload = {
                "type": cmd,
                "id": msg_id,
                "code": "200",
                "msg": "OK",
                "data": reply,
            }
            await connection.send(json.dumps(payload))

    def _handle_command(self, cmd: str | None, params: dict) -> dict:
        if cmd == "vnd.logitech.harmony/vnd.logitech.harmony.engine?config":
            return self.state.config
        if cmd == "vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity":
            return {"result": self.state.current_activity}
        if cmd == "vnd.logitech.connect/vnd.logitech.statedigest?get":
            return {
                "activityId": self.state.current_activity,
                "configVersion": self.state.config.get("configVersion"),
            }
        if cmd == "vnd.logitech.harmony/vnd.logitech.harmony.engine?startactivity":
            self.state.current_activity = str(params.get("activityId", "-1"))
            return {"ok": True}
        if cmd == "harmony.activityengine?runactivity":
            self.state.current_activity = str(params.get("activityId", "-1"))
            return {"ok": True}
        if cmd == "vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction":
            self.state.received_commands.append(
                {"params": params, "timestamp": time.time()}
            )
            return {"ok": True}
        if cmd == "harmony.engine?changeChannel":
            self.state.received_commands.append(
                {"changeChannel": params.get("channel")}
            )
            return {"ok": True}
        return {}

    async def push_event(self, type_: str, data: dict) -> None:
        if self._ws_server is None:
            return
        message = json.dumps({"type": type_, "data": data})
        for ws in list(getattr(self._ws_server, "connections", [])):
            with contextlib.suppress(Exception):
                await ws.send(message)


async def run_forever(host: str = "127.0.0.1") -> None:  # pragma: no cover
    async with FakeHub(host) as hub:
        _LOG.info("FakeHub WS %s:%d", hub.host, hub.ws_port)
        await asyncio.Future()
