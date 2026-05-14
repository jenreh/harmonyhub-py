"""FastMCP server exposing Harmony Hub control over stdio.

All log output goes to stderr — stdout is reserved for MCP framing. The host
defaults to `HARMONY_HUB_HOST` (env or config.toml). A single
``HarmonyHubClient`` instance is reused across tool calls.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from harmonyhub.client import HarmonyHubClient
from harmonyhub.config import load as load_app_config

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
_LOG = logging.getLogger("harmonyhub.mcp")

mcp = FastMCP("harmony")
_client: HarmonyHubClient | None = None


def _host() -> str:
    cfg = load_app_config()
    host = os.environ.get("HARMONY_HUB_HOST") or cfg.host
    if not host:
        raise RuntimeError(
            "No hub host configured. Set HARMONY_HUB_HOST or [hub].host in config.toml."
        )
    return host


async def _get_client() -> HarmonyHubClient:
    global _client
    if _client is None:
        _client = HarmonyHubClient(_host(), connection_mode="persistent")
        await _client.connect()
    return _client


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


# ----------------------------------------------------------------------- tools


@mcp.tool()
async def harmony_get_status() -> dict:
    """Return current activity, last channel, connection state."""
    client = await _get_client()
    return _jsonable(await client.get_status())


@mcp.tool()
async def harmony_list_activities() -> list[dict]:
    """List all activities defined on the hub."""
    client = await _get_client()
    return _jsonable(await client.list_activities())


@mcp.tool()
async def harmony_start_activity(activity: str) -> dict:
    """Start an activity by name or id. Destructive: powers devices on."""
    client = await _get_client()
    return _jsonable(await client.start_activity(activity))


@mcp.tool()
async def harmony_power_off() -> dict:
    """Run the PowerOff activity. Destructive."""
    client = await _get_client()
    return _jsonable(await client.power_off())


@mcp.tool()
async def harmony_list_devices() -> list[dict]:
    """List all devices on the hub."""
    client = await _get_client()
    return _jsonable(await client.list_devices())


@mcp.tool()
async def harmony_list_device_commands(device: str) -> list[str]:
    """List commands available on a device (by id, label, or substring)."""
    client = await _get_client()
    return await client.list_device_commands(device)


@mcp.tool()
async def harmony_device_power_on(device: str) -> dict:
    """Power on a single device (PowerOn or PowerToggle fallback)."""
    client = await _get_client()
    return _jsonable(await client.device_power_on(device))


@mcp.tool()
async def harmony_device_power_off(device: str) -> dict:
    """Power off a single device (PowerOff)."""
    client = await _get_client()
    return _jsonable(await client.device_power_off(device))


@mcp.tool()
async def harmony_send_key(
    key: Literal[
        "volume_up",
        "volume_down",
        "mute",
        "channel_up",
        "channel_down",
        "digit_0",
        "digit_1",
        "digit_2",
        "digit_3",
        "digit_4",
        "digit_5",
        "digit_6",
        "digit_7",
        "digit_8",
        "digit_9",
        "ok",
        "enter",
        "back",
        "off",
    ],
    device: str | None = None,
    activity: str | None = None,
) -> dict:
    """Send a logical key (auto-routed via activity routes when device is omitted)."""
    client = await _get_client()
    return _jsonable(await client.send_key(key, device=device, activity=activity))


@mcp.tool()
async def harmony_send_command(device: str, command: str, hold_ms: int = 0) -> dict:
    """Send a raw IR command to a device. Bypasses logical-key routing."""
    client = await _get_client()
    return _jsonable(await client.send_command(device, command, hold_ms=hold_ms))


@mcp.tool()
async def harmony_set_channel(channel: str, device: str | None = None) -> dict:
    """Switch channels (digits_then_enter or change_channel per config)."""
    client = await _get_client()
    return _jsonable(await client.set_channel(channel, device=device))


@mcp.tool()
async def harmony_refresh_config() -> dict:
    """Force-refresh the cached hub config."""
    client = await _get_client()
    cfg = await client.get_config(refresh=True)
    return {
        "activities": len(cfg.activities),
        "devices": len(cfg.devices),
        "config_version": cfg.config_version,
    }


# ------------------------------------------------------------------- resources


@mcp.resource("harmony://activities")
async def res_activities() -> str:
    client = await _get_client()
    return json.dumps(_jsonable(await client.list_activities()))


@mcp.resource("harmony://devices")
async def res_devices() -> str:
    client = await _get_client()
    return json.dumps(_jsonable(await client.list_devices()))


@mcp.resource("harmony://status")
async def res_status() -> str:
    client = await _get_client()
    return json.dumps(_jsonable(await client.get_status()))


@mcp.resource("harmony://config")
async def res_config() -> str:
    client = await _get_client()
    cfg = await client.get_config()
    return json.dumps(cfg.raw)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
