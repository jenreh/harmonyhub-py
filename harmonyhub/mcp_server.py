import json
import logging
import os
import sys
from typing import Literal

from fastmcp import FastMCP

from harmonyhub.service import HarmonyService, to_jsonable

# Route all logs to stderr — stdout is reserved for the MCP transport.
# Set HARMONY_DEBUG=1 to enable developer-mode logging (DEBUG level).
_log_level = logging.DEBUG if os.environ.get("HARMONY_DEBUG") == "1" else logging.ERROR
logging.basicConfig(
    stream=sys.stderr,
    level=_log_level,
    format="%(levelname)s %(name)s: %(message)s",
)
_LOG = logging.getLogger("harmony.mcp")

mcp = FastMCP(
    "harmony",
    instructions=(
        "Local control of a Logitech Harmony Hub. "
        "Tools control activities, devices, and channels on the local network. "
        "Destructive operations (power-off, start-activity) take effect immediately."
    ),
)


_service: HarmonyService | None = None


async def _get_service() -> HarmonyService:
    global _service
    if _service is None:
        _service = HarmonyService(connection_mode="persistent")
        await _service.connect()
    return _service


# --------------------------------------------------------------------- tools


@mcp.tool()
async def harmony_get_status() -> dict:
    """Return current activity, last channel (with source), and connection state."""
    service = await _get_service()
    return to_jsonable(await service.client.get_status())


@mcp.tool()
async def harmony_list_activities() -> list[dict]:
    """List all configured Harmony activities."""
    service = await _get_service()
    return to_jsonable(await service.client.list_activities())


@mcp.tool()
async def harmony_start_activity(activity: str) -> dict:
    """Start an activity by name or id. Destructive: switches the hub immediately."""
    service = await _get_service()
    return to_jsonable(await service.client.start_activity(activity))


@mcp.tool()
async def harmony_power_off() -> dict:
    """Run the PowerOff activity. Destructive: turns off all devices in the active activity."""
    service = await _get_service()
    return to_jsonable(await service.client.power_off())


@mcp.tool()
async def harmony_list_devices() -> list[dict]:
    """List all configured Harmony devices."""
    service = await _get_service()
    return to_jsonable(await service.client.list_devices())


@mcp.tool()
async def harmony_list_device_commands(device: str) -> list[str]:
    """List all available IR commands for a device (by name or id)."""
    service = await _get_service()
    return await service.client.list_device_commands(device)


@mcp.tool()
async def harmony_device_power_on(device: str) -> dict:
    """Power on a device (PowerOn → falls back to PowerToggle if enabled)."""
    service = await _get_service()
    return to_jsonable(await service.client.device_power_on(device))


@mcp.tool()
async def harmony_device_power_off(device: str) -> dict:
    """Power off a single device (sends PowerOff)."""
    service = await _get_service()
    return to_jsonable(await service.client.device_power_off(device))


@mcp.tool()
async def harmony_send_key(
    key: Literal[
        "volume_up",
        "volume_down",
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
    """Send a logical key. Routing falls back to TOML activity routes, then auto-resolution."""
    service = await _get_service()
    return to_jsonable(
        await service.client.send_key(key, device=device, activity=activity)
    )


@mcp.tool()
async def harmony_send_command(device: str, command: str, hold_ms: int = 0) -> dict:
    """Send a raw Harmony IR command. Use for vendor-specific buttons not covered by send_key."""
    service = await _get_service()
    return to_jsonable(
        await service.client.send_command(device, command, hold_ms=hold_ms)
    )


@mcp.tool()
async def harmony_set_channel(channel: str, device: str | None = None) -> dict:
    """Set a channel (digits_then_enter or change_channel depending on config)."""
    service = await _get_service()
    return to_jsonable(await service.client.set_channel(channel, device=device))


@mcp.tool()
async def harmony_refresh_config() -> dict:
    """Re-fetch the hub configuration and replace the cache."""
    service = await _get_service()
    config = await service.client.get_config(refresh=True)
    return {
        "activities": len(config.activities),
        "devices": len(config.devices),
        "config_version": config.config_version,
    }


# --------------------------------------------------------------------- resources


@mcp.resource("harmony://config")
async def resource_config() -> str:
    service = await _get_service()
    config = await service.client.get_config()
    payload = {
        "activities": to_jsonable(list(config.activities)),
        "devices": to_jsonable(list(config.devices)),
        "config_version": config.config_version,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


@mcp.resource("harmony://activities")
async def resource_activities() -> str:
    service = await _get_service()
    return json.dumps(
        to_jsonable(await service.client.list_activities()), indent=2, sort_keys=True
    )


@mcp.resource("harmony://devices")
async def resource_devices() -> str:
    service = await _get_service()
    return json.dumps(
        to_jsonable(await service.client.list_devices()), indent=2, sort_keys=True
    )


@mcp.resource("harmony://status")
async def resource_status() -> str:
    service = await _get_service()
    return json.dumps(
        to_jsonable(await service.client.get_status()), indent=2, sort_keys=True
    )


def main() -> None:
    """Console-script entry point: run the MCP server over stdio."""
    try:
        mcp.run()
    except KeyboardInterrupt:
        pass
    finally:
        if _service is not None:
            import asyncio as _asyncio

            try:
                _asyncio.run(_service.close())
            except RuntimeError:
                pass
