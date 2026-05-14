"""High-level Harmony Hub client.

Wraps HTTP provisioning + WebSocket transport into a friendly async API.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, Literal

from harmonyhub import aliases
from harmonyhub.cache import hub_cache_dir, read_json, write_json
from harmonyhub.config import AppConfig
from harmonyhub.config import load as load_app_config
from harmonyhub.exceptions import (
    AmbiguousRoutingError,
    CommandNotFoundError,
    HarmonyHubError,
    HubUnavailableError,
    ProtocolError,
)
from harmonyhub.models import (
    Activity,
    ActivityStatus,
    ChannelResult,
    CommandResult,
    Device,
    HubConfig,
    HubEvent,
    HubInfo,
    HubStatus,
    LogicalKey,
)
from harmonyhub.protocol.http import ProvisionInfo, fetch_provision_info
from harmonyhub.protocol.websocket import WebSocketTransport
from harmonyhub.status import RuntimeState, load_state, save_state

_LOG = logging.getLogger(__name__)

_POWER_OFF_ID = "-1"

_CMD_CONFIG = "vnd.logitech.harmony/vnd.logitech.harmony.engine?config"
_CMD_CURRENT_ACTIVITY = (
    "vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity"
)
_CMD_STATE_DIGEST = "vnd.logitech.connect/vnd.logitech.statedigest?get"
_CMD_START_ACTIVITY = "vnd.logitech.harmony/vnd.logitech.harmony.engine?startactivity"
_CMD_START_ACTIVITY_FALLBACK = "harmony.activityengine?runactivity"
_CMD_HOLD_ACTION = "vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction"
_CMD_CHANGE_CHANNEL = "harmony.engine?changeChannel"

ConnectionMode = Literal["persistent", "ondemand"]


def _now_ms() -> str:
    import time

    return str(int(time.time() * 1000))


class HarmonyHubClient:
    """High-level async client for a single Harmony Hub."""

    def __init__(
        self,
        host: str,
        *,
        connection_mode: ConnectionMode = "ondemand",
        app_config: AppConfig | None = None,
        keepalive_interval_s: float | None = None,
        request_timeout_s: float | None = None,
    ) -> None:
        self._host = host
        self._mode: ConnectionMode = connection_mode
        self._app_config: AppConfig = app_config or load_app_config()

        conn = self._app_config.connection
        self._keepalive = keepalive_interval_s or conn.keepalive_interval_s
        self._request_timeout = request_timeout_s or conn.request_timeout_s

        self._provision: ProvisionInfo | None = None
        self._transport: WebSocketTransport | None = None
        self._info: HubInfo | None = None
        self._config: HubConfig | None = None
        self._state: RuntimeState = RuntimeState()
        self._state_loaded = False

    # ---------------------------------------------------------------- lifecycle

    async def __aenter__(self) -> HarmonyHubClient:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._transport is not None:
            return
        self._provision = await fetch_provision_info(
            self._host, timeout=self._request_timeout
        )
        self._transport = WebSocketTransport(
            self._host,
            self._provision,
            keepalive_interval_s=self._keepalive,
            request_timeout_s=self._request_timeout,
            persistent=self._mode == "persistent",
        )
        await self._transport.connect()
        self._info = self._build_info(self._provision)
        self._state = load_state(self._provision.remote_id)
        self._state_loaded = True

    async def close(self) -> None:
        if self._transport is not None:
            await self._transport.close()
            self._transport = None

    def _require_transport(self) -> WebSocketTransport:
        if self._transport is None:
            raise HarmonyHubError("Client is not connected. Call connect() first.")
        return self._transport

    # ----------------------------------------------------------------- hub info

    def _build_info(self, prov: ProvisionInfo) -> HubInfo:
        raw = prov.raw or {}
        firmware = raw.get("currentFwVersion")
        if isinstance(raw.get("hubProfiles"), dict):
            firmware = raw["hubProfiles"].get("Harmony", firmware)
        return HubInfo(
            host=self._host,
            remote_id=prov.remote_id,
            account_id=prov.account_id,
            email_redacted=prov.email_redacted,
            discovery_server=prov.discovery_server,
            firmware_version=firmware,
            friendly_name=raw.get("friendlyName") or raw.get("name"),
        )

    async def get_info(self) -> HubInfo:
        if self._info is None:
            prov = await fetch_provision_info(self._host, timeout=self._request_timeout)
            self._info = self._build_info(prov)
        return self._info

    # ------------------------------------------------------------------- config

    async def get_config(self, refresh: bool = False) -> HubConfig:
        if self._config is not None and not refresh:
            return self._config
        transport = self._require_transport()
        body = await transport.request(_CMD_CONFIG)
        data = body.get("data") or {}
        config = _parse_config(data)
        self._config = config
        if self._provision is not None:
            cache_path = hub_cache_dir(self._provision.remote_id) / "config.json"
            try:
                write_json(cache_path, {"data": data})
            except OSError as exc:
                _LOG.warning("Failed to write config cache: %s", exc)
        return config

    async def list_activities(self) -> list[Activity]:
        config = await self.get_config()
        return list(config.activities)

    async def list_devices(self) -> list[Device]:
        config = await self.get_config()
        return list(config.devices)

    async def list_device_commands(self, device: str | int) -> list[str]:
        dev = await self._resolve_device(device)
        return list(dev.commands)

    # ------------------------------------------------------------------- status

    async def get_current_activity(self) -> ActivityStatus:
        transport = self._require_transport()
        body = await transport.request(_CMD_CURRENT_ACTIVITY)
        data = body.get("data") or {}
        activity_id = str(data.get("result") or data.get("activityId") or _POWER_OFF_ID)
        label = await self._activity_label(activity_id)
        return ActivityStatus(activity_id=activity_id, activity_label=label)

    async def get_status(self) -> HubStatus:
        current = await self.get_current_activity()
        digest_version: int | None = None
        try:
            digest_body = await self._require_transport().request(_CMD_STATE_DIGEST)
            digest_data = digest_body.get("data") or {}
            version = digest_data.get("configVersion")
            if isinstance(version, int):
                digest_version = version
        except (ProtocolError, HubUnavailableError):
            digest_version = None
        return HubStatus(
            current_activity=current,
            last_channel=self._state.last_channel,
            last_channel_source=self._state.last_channel_source,
            connected=self._transport is not None and self._transport.connected,
            config_version=digest_version,
        )

    async def listen(self) -> AsyncIterator[HubEvent]:
        """Yield spontaneous hub events until ``close()`` is called."""
        transport = self._require_transport()
        async for event in transport.events():
            yield event

    # --------------------------------------------------------------- activities

    async def start_activity(self, activity: str | int) -> ActivityStatus:
        target = await self._resolve_activity(activity)
        params = {"activityId": target.id, "timestamp": _now_ms()}
        try:
            await self._require_transport().request(_CMD_START_ACTIVITY, params)
        except (ProtocolError, HubUnavailableError) as primary:
            _LOG.info("startactivity failed (%s); falling back to runactivity", primary)
            await self._require_transport().request(
                _CMD_START_ACTIVITY_FALLBACK, params
            )
        return ActivityStatus(
            activity_id=target.id,
            activity_label=target.label,
            transition_state="starting",
        )

    async def power_off(self) -> ActivityStatus:
        return await self.start_activity(_POWER_OFF_ID)

    # ------------------------------------------------------------------ devices

    async def device_power_on(self, device: str | int) -> CommandResult:
        dev = await self._resolve_device(device)
        chain = (
            aliases.candidates_for("power_on_fallback")
            if self._app_config.power_on_fallback_toggle
            else aliases.candidates_for("power_on")
        )
        try:
            command = _first_present(chain, dev.commands)
        except CommandNotFoundError as exc:
            return CommandResult(
                device_id=dev.id, command="PowerOn", success=False, error=str(exc)
            )
        return await self.send_command(dev.id, command)

    async def device_power_off(self, device: str | int) -> CommandResult:
        dev = await self._resolve_device(device)
        try:
            command = _first_present(aliases.candidates_for("power_off"), dev.commands)
        except CommandNotFoundError as exc:
            return CommandResult(
                device_id=dev.id, command="PowerOff", success=False, error=str(exc)
            )
        return await self.send_command(dev.id, command)

    # ----------------------------------------------------------------- commands

    async def send_command(
        self, device: str | int, command: str, hold_ms: int = 0
    ) -> CommandResult:
        dev = await self._resolve_device(device)
        if command not in dev.commands:
            raise CommandNotFoundError(command, dev.label, available=list(dev.commands))
        ir_command = dev.command_actions.get(command, command)
        try:
            await self._press_release(dev.id, ir_command, hold_ms=hold_ms)
        except (ProtocolError, HubUnavailableError) as exc:
            return CommandResult(
                device_id=dev.id, command=command, success=False, error=str(exc)
            )
        return CommandResult(device_id=dev.id, command=command, success=True)

    async def send_key(
        self,
        key: LogicalKey | str,
        device: str | int | None = None,
        activity: str | None = None,
    ) -> CommandResult:
        if key == "off":
            await self.power_off()
            return CommandResult(device_id=_POWER_OFF_ID, command="off", success=True)

        target_device = await self._route_for_key(key, device=device, activity=activity)
        try:
            command = aliases.resolve(
                key, target_device.commands, device_label=target_device.label
            )
        except CommandNotFoundError as exc:
            return CommandResult(
                device_id=target_device.id,
                command=str(key),
                success=False,
                error=str(exc),
            )

        if key in ("volume_up", "volume_down"):
            return await self._send_repeated(
                target_device.id,
                command,
                repeat=self._app_config.volume.repeat,
                hold_ms=self._app_config.volume.hold_ms,
                inter_press_delay_ms=self._app_config.volume.inter_press_delay_ms,
            )
        return await self.send_command(target_device.id, command)

    async def _send_repeated(
        self,
        device_id: str,
        command: str,
        *,
        repeat: int,
        hold_ms: int,
        inter_press_delay_ms: int,
    ) -> CommandResult:
        last: CommandResult | None = None
        for i in range(max(1, repeat)):
            last = await self.send_command(device_id, command, hold_ms=hold_ms)
            if not last.success:
                return last
            if i < repeat - 1 and inter_press_delay_ms > 0:
                await asyncio.sleep(inter_press_delay_ms / 1000.0)
        assert last is not None
        return last

    async def _press_release(
        self, device_id: str, ir_command: str, *, hold_ms: int
    ) -> None:
        # The `action` field is a JSON-encoded string whose `command` value
        # must match what the hub published in its config (the inner IR
        # command, e.g. "1" for "Number1"). Sending the function name
        # instead yields hub error code 566 "Command not found".
        action = _json.dumps(
            {"command": ir_command, "type": "IRCommand", "deviceId": device_id},
            separators=(",", ":"),
        )
        transport = self._require_transport()
        # holdAction is fire-and-forget: the hub does not send a correlated
        # reply for press/release, so awaiting one would always time out.
        await transport.notify(
            _CMD_HOLD_ACTION,
            {"status": "press", "timestamp": "0", "verb": "render", "action": action},
        )
        wait_s = max(hold_ms, 100) / 1000.0
        await asyncio.sleep(wait_s)
        await transport.notify(
            _CMD_HOLD_ACTION,
            {
                "status": "release",
                "timestamp": str(max(hold_ms, 100)),
                "verb": "render",
                "action": action,
            },
        )

    # ------------------------------------------------------------------ channel

    async def set_channel(
        self, channel: str | int, device: str | int | None = None
    ) -> ChannelResult:
        channel_str = str(channel).strip()
        if not channel_str.isdigit():
            return ChannelResult(
                channel=channel_str,
                method=self._app_config.channel.mode,
                success=False,
                error=f"Channel must be all digits, got {channel_str!r}",
            )

        target_device = await self._route_for_key("digit_0", device=device)

        if self._app_config.channel.mode == "change_channel":
            try:
                await self._require_transport().request(
                    _CMD_CHANGE_CHANNEL,
                    {"channel": channel_str, "timestamp": _now_ms()},
                )
            except (ProtocolError, HubUnavailableError) as exc:
                return ChannelResult(
                    channel=channel_str,
                    method="change_channel",
                    success=False,
                    error=str(exc),
                )
            self._record_channel(channel_str)
            return ChannelResult(
                channel=channel_str, method="change_channel", success=True
            )

        delay_s = self._app_config.channel.inter_digit_delay_ms / 1000.0
        for digit in channel_str:
            try:
                command = aliases.resolve(
                    f"digit_{digit}",
                    target_device.commands,
                    device_label=target_device.label,
                )
            except CommandNotFoundError as exc:
                return ChannelResult(
                    channel=channel_str,
                    method="digits_then_enter",
                    success=False,
                    error=str(exc),
                )
            result = await self.send_command(target_device.id, command)
            if not result.success:
                return ChannelResult(
                    channel=channel_str,
                    method="digits_then_enter",
                    success=False,
                    error=result.error,
                )
            await asyncio.sleep(delay_s)

        if self._app_config.channel.send_enter:
            try:
                enter = aliases.resolve(
                    "enter", target_device.commands, device_label=target_device.label
                )
                await self.send_command(target_device.id, enter)
            except CommandNotFoundError:
                _LOG.info(
                    "No Enter/OK command on %s; channel sent without confirm",
                    target_device.label,
                )

        self._record_channel(channel_str)
        return ChannelResult(
            channel=channel_str, method="digits_then_enter", success=True
        )

    def _record_channel(self, channel: str) -> None:
        self._state = replace(
            self._state, last_channel=channel, last_channel_source="library"
        )
        if self._provision is not None:
            save_state(self._provision.remote_id, self._state)

    # ---------------------------------------------------------------- resolvers

    async def _resolve_activity(self, activity: str | int) -> Activity:
        config = await self.get_config()
        key = str(activity)
        for cand in config.activities:
            if cand.id == key:
                return cand
        lowered = key.casefold()
        for cand in config.activities:
            if cand.label.casefold() == lowered:
                return cand
        matches = [c for c in config.activities if lowered in c.label.casefold()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise HarmonyHubError(
                f"Activity {activity!r} not found. Known: {[c.label for c in config.activities]}"
            )
        raise AmbiguousRoutingError(
            key=str(activity), candidates=[c.label for c in matches]
        )

    async def _resolve_device(self, device: str | int) -> Device:
        config = await self.get_config()
        key = str(device)
        for cand in config.devices:
            if cand.id == key:
                return cand
        lowered = key.casefold()
        for cand in config.devices:
            if cand.label.casefold() == lowered:
                return cand
        matches = [c for c in config.devices if lowered in c.label.casefold()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise HarmonyHubError(
                f"Device {device!r} not found. Known: {[c.label for c in config.devices]}"
            )
        raise AmbiguousRoutingError(
            key=str(device), candidates=[c.label for c in matches]
        )

    async def _activity_label(self, activity_id: str) -> str | None:
        if activity_id == _POWER_OFF_ID:
            return "PowerOff"
        try:
            config = await self.get_config()
        except (ProtocolError, HubUnavailableError):
            return None
        for activity in config.activities:
            if activity.id == activity_id:
                return activity.label
        return None

    async def _route_for_key(
        self,
        key: LogicalKey | str,
        *,
        device: str | int | None,
        activity: str | None = None,
    ) -> Device:
        if device is not None:
            return await self._resolve_device(device)

        active_label = activity
        if active_label is None:
            try:
                current = await self.get_current_activity()
                active_label = current.activity_label
            except (ProtocolError, HubUnavailableError):
                active_label = None

        route = self._app_config.activity_routes.get(active_label or "")
        configured = _route_device_for_key(route, key)
        if configured:
            return await self._resolve_device(configured)

        config = await self.get_config()
        chain = aliases.candidates_for(key) or (str(key),)
        candidates = [d for d in config.devices if any(c in d.commands for c in chain)]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise CommandNotFoundError(
                str(key),
                device="<auto>",
                available=sorted({c for d in config.devices for c in d.commands}),
            )
        raise AmbiguousRoutingError(
            key=str(key), candidates=[d.label for d in candidates]
        )


def _route_device_for_key(route: object, key: str) -> str | None:
    if route is None:
        return None
    if key in ("volume_up", "volume_down", "mute"):
        return getattr(route, "volume_device", None)
    if key in ("channel_up", "channel_down"):
        return getattr(route, "channel_device", None)
    if key.startswith("digit_"):
        return getattr(route, "number_device", None) or getattr(
            route, "channel_device", None
        )
    if key in ("ok", "enter", "back"):
        return getattr(route, "navigation_device", None)
    return None


def _first_present(chain: tuple[str, ...], available: tuple[str, ...]) -> str:
    pool = set(available)
    for candidate in chain:
        if candidate in pool:
            return candidate
    raise CommandNotFoundError(chain[0], device="<unknown>", available=sorted(pool))


def _parse_config(data: dict[str, Any]) -> HubConfig:
    activities: list[Activity] = []
    for item in data.get("activity") or []:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id", ""))
        if not aid:
            continue
        activities.append(
            Activity(
                id=aid,
                label=str(item.get("label") or aid),
                is_power_off=aid == _POWER_OFF_ID,
            )
        )

    raw_devices = data.get("device") or []
    devices: list[Device] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("id", ""))
        if not device_id:
            continue
        commands: list[str] = []
        command_actions: dict[str, str] = {}
        for group in item.get("controlGroup") or []:
            if not isinstance(group, dict):
                continue
            for func in group.get("function") or []:
                if not isinstance(func, dict):
                    continue
                name = func.get("name")
                if not name:
                    continue
                name_str = str(name)
                commands.append(name_str)
                action_raw = func.get("action")
                if isinstance(action_raw, str):
                    try:
                        action_obj = _json.loads(action_raw)
                    except (ValueError, TypeError):
                        continue
                    ir_cmd = (
                        action_obj.get("command")
                        if isinstance(action_obj, dict)
                        else None
                    )
                    if ir_cmd:
                        command_actions[name_str] = str(ir_cmd)
        devices.append(
            Device(
                id=device_id,
                label=str(item.get("label") or device_id),
                manufacturer=item.get("manufacturer"),
                model=item.get("model"),
                commands=tuple(dict.fromkeys(commands)),
                command_actions=command_actions,
            )
        )

    return HubConfig(
        activities=tuple(activities),
        devices=tuple(devices),
        config_version=data.get("configVersion")
        if isinstance(data.get("configVersion"), int)
        else None,
        raw=data,
    )


__all__ = ["HarmonyHubClient"]


def _read_cached_config(hub_id: str) -> dict[str, Any] | None:
    return read_json(hub_cache_dir(hub_id) / "config.json")
