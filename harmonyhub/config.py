"""TOML configuration loading and environment-variable overlay.

Precedence (highest first): explicit argument → env var → TOML file → default.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from harmonyhub.cache import config_file

ConnectionMode = Literal["persistent", "ondemand"]
Protocol = Literal["websocket", "xmpp"]
ChannelMode = Literal["digits_then_enter", "change_channel"]


@dataclass(frozen=True)
class ConnectionConfig:
    mode: ConnectionMode = "ondemand"
    protocol: Protocol = "websocket"
    keepalive_interval_s: float = 50.0
    request_timeout_s: float = 10.0


@dataclass(frozen=True)
class ChannelConfig:
    mode: ChannelMode = "digits_then_enter"
    inter_digit_delay_ms: int = 150
    send_enter: bool = True


@dataclass(frozen=True)
class VolumeConfig:
    # Number of IR presses per logical volume key. Useful when the receiver's
    # IR step size is finer than the desired user step (e.g. Yamaha AVRs use
    # 0.5 dB per press — set repeat=4 to get 2 dB per `key volume-up`).
    repeat: int = 1
    # Hold duration of each IR press in milliseconds. Some receivers ignore
    # very short presses or require a held signal for repeat-frames.
    hold_ms: int = 0
    # Delay between successive presses when repeat > 1.
    inter_press_delay_ms: int = 80


@dataclass(frozen=True)
class ActivityRoute:
    volume_device: str | None = None
    channel_device: str | None = None
    navigation_device: str | None = None
    number_device: str | None = None


@dataclass(frozen=True)
class AppConfig:
    host: str | None = None
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    activity_routes: dict[str, ActivityRoute] = field(default_factory=dict)
    power_on_fallback_toggle: bool = True


def load(path: Path | None = None) -> AppConfig:
    """Load configuration from TOML file (if present) and overlay env vars."""
    raw: dict = {}
    target = path or config_file()
    if target.exists():
        raw = tomllib.loads(target.read_text(encoding="utf-8"))

    hub = raw.get("hub", {})
    conn = raw.get("connection", {})
    chan = raw.get("channel", {})
    vol = raw.get("volume", {})
    routes_raw = raw.get("activity_routes", {})

    host = os.environ.get("HARMONY_HUB_HOST") or hub.get("host")
    protocol = os.environ.get("HARMONY_PROTOCOL") or conn.get("protocol", "websocket")
    mode = os.environ.get("HARMONY_CONNECTION_MODE") or conn.get("mode", "ondemand")

    connection = ConnectionConfig(
        mode=mode,  # type: ignore[arg-type]
        protocol=protocol,  # type: ignore[arg-type]
        keepalive_interval_s=float(conn.get("keepalive_interval_s", 50.0)),
        request_timeout_s=float(conn.get("request_timeout_s", 10.0)),
    )
    channel = ChannelConfig(
        mode=chan.get("mode", "digits_then_enter"),
        inter_digit_delay_ms=int(chan.get("inter_digit_delay_ms", 150)),
        send_enter=bool(chan.get("send_enter", True)),
    )
    volume = VolumeConfig(
        repeat=max(1, int(vol.get("repeat", 1))),
        hold_ms=max(0, int(vol.get("hold_ms", 0))),
        inter_press_delay_ms=max(0, int(vol.get("inter_press_delay_ms", 80))),
    )
    activity_routes: dict[str, ActivityRoute] = {}
    for name, payload in routes_raw.items():
        if not isinstance(payload, dict):
            continue
        activity_routes[name] = ActivityRoute(
            volume_device=payload.get("volume_device"),
            channel_device=payload.get("channel_device"),
            navigation_device=payload.get("navigation_device"),
            number_device=payload.get("number_device"),
        )

    return AppConfig(
        host=host,
        connection=connection,
        channel=channel,
        volume=volume,
        activity_routes=activity_routes,
    )
