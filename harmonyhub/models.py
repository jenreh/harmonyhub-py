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

DeviceKind = Literal[
    "television",
    "avreceiver",
    "speaker",
    "stb",
    "game",
    "appletv",
    "other",
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
class ActivityRoles:
    volume_device_id: str | None = None
    channel_device_id: str | None = None
    display_device_id: str | None = None


@dataclass(frozen=True, slots=True)
class PowerAction:
    command: str
    order: int = 0
    duration_ms: int | None = None
    action_type: str | None = None


@dataclass(frozen=True, slots=True)
class PowerFeatures:
    on: tuple[PowerAction, ...] = ()
    off: tuple[PowerAction, ...] = ()


@dataclass(frozen=True, slots=True)
class FixitState:
    device_id: str
    is_manual_power: bool = False
    power: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SequenceAction:
    command: str | None = None
    device_id: str | None = None
    delay_ms: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Sequence:
    id: str
    label: str
    actions: tuple[SequenceAction, ...] = ()


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    label: str
    is_power_off: bool = False
    type: str | None = None
    is_av_activity: bool = False
    order: int | None = None
    roles: ActivityRoles = field(default_factory=ActivityRoles)
    control_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    fixit: tuple[FixitState, ...] = ()


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
    type: str | None = None
    kind: DeviceKind | None = None
    command_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    power_features: PowerFeatures | None = None
    is_manual_power: bool = False
    capabilities: tuple[int, ...] = ()
    capability_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContentEndpoints:
    device_host: str | None = None
    image_host: str | None = None
    service_host: str | None = None
    user_host: str | None = None
    household_user_profile_uri: str | None = None


@dataclass(frozen=True, slots=True)
class HubConfig:
    activities: tuple[Activity, ...]
    devices: tuple[Device, ...]
    config_version: int | None = None
    locale: str | None = None
    sequences: tuple[Sequence, ...] = ()
    content: ContentEndpoints | None = None
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
