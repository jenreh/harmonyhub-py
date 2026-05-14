"""Frozen dataclasses for the Harmony Hub domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LogicalKey = Literal[
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
]


@dataclass(frozen=True, slots=True)
class HubInfo:
    host: str
    remote_id: str
    account_id: str | None = None
    email_redacted: str | None = None
    discovery_server: str | None = None
    firmware_version: str | None = None
    friendly_name: str | None = None


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    label: str
    is_power_off: bool = False


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    label: str
    manufacturer: str | None
    model: str | None
    commands: tuple[str, ...]
    # Maps function name (e.g. "Number1") to the IR command the hub expects
    # (e.g. "1"). The hub publishes both in its config; the function name is
    # what users see, but the IR command is what holdAction wants.
    command_actions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HubConfig:
    activities: tuple[Activity, ...]
    devices: tuple[Device, ...]
    config_version: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivityStatus:
    activity_id: str
    activity_label: str | None = None
    transition_state: str | None = None


@dataclass(frozen=True, slots=True)
class HubStatus:
    current_activity: ActivityStatus
    last_channel: str | None
    last_channel_source: Literal["library", "harmony", "unknown"]
    connected: bool
    config_version: int | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    device_id: str
    command: str
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelResult:
    channel: str
    method: str
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class HubEvent:
    type: str
    data: dict
    raw: dict = field(default_factory=dict)
