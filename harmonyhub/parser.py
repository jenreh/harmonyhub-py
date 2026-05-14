"""Typed parser for the Harmony Hub raw configuration payload.

Splits the dict-walk that used to live in ``client._parse_config`` into focused
helpers per top-level key (``device``, ``activity``, ``sequence``, ``content``,
``global``). Unknown / malformed entries are skipped silently so the parser
stays tolerant of firmware variants.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from harmonyhub.capabilities import labels_for
from harmonyhub.models import (
    Activity,
    ActivityRoles,
    ContentEndpoints,
    Device,
    DeviceKind,
    FixitState,
    HubConfig,
    PowerAction,
    PowerFeatures,
    Sequence,
    SequenceAction,
)

_LOG = logging.getLogger(__name__)

_POWER_OFF_ID = "-1"


def parse_config(data: dict[str, Any]) -> HubConfig:
    """Parse the hub's raw ``config`` payload into a typed :class:`HubConfig`."""
    devices: list[Device] = []
    for item in data.get("device") or []:
        if not isinstance(item, dict):
            continue
        parsed = _parse_device(item)
        if parsed is not None:
            devices.append(parsed)

    activities: list[Activity] = []
    for item in data.get("activity") or []:
        if not isinstance(item, dict):
            continue
        parsed_activity = _parse_activity(item)
        if parsed_activity is not None:
            activities.append(parsed_activity)

    sequences: list[Sequence] = []
    for item in data.get("sequence") or []:
        if not isinstance(item, dict):
            continue
        parsed_seq = _parse_sequence(item)
        if parsed_seq is not None:
            sequences.append(parsed_seq)

    locale: str | None = None
    global_block = data.get("global")
    if isinstance(global_block, dict):
        loc = global_block.get("locale")
        if isinstance(loc, str):
            locale = loc

    content = _parse_content(data.get("content"))
    version = data.get("configVersion")

    return HubConfig(
        activities=tuple(activities),
        devices=tuple(devices),
        config_version=version if isinstance(version, int) else None,
        locale=locale,
        sequences=tuple(sequences),
        content=content,
        raw=data,
    )


# --------------------------------------------------------------------- device


def _parse_device(item: dict[str, Any]) -> Device | None:
    device_id = str(item.get("id", ""))
    if not device_id:
        return None

    commands: list[str] = []
    command_actions: dict[str, str] = {}
    command_groups: dict[str, tuple[str, ...]] = {}

    for group in item.get("controlGroup") or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "Misc")
        group_commands: list[str] = []
        for func in group.get("function") or []:
            if not isinstance(func, dict):
                continue
            name = func.get("name")
            if not name:
                continue
            name_str = str(name)
            commands.append(name_str)
            group_commands.append(name_str)
            action_raw = func.get("action")
            if isinstance(action_raw, str):
                try:
                    action_obj = _json.loads(action_raw)
                except (ValueError, TypeError):
                    continue
                ir_cmd = (
                    action_obj.get("command") if isinstance(action_obj, dict) else None
                )
                if ir_cmd:
                    command_actions[name_str] = str(ir_cmd)
        if group_commands:
            existing = command_groups.get(group_name, ())
            command_groups[group_name] = tuple(
                dict.fromkeys((*existing, *group_commands))
            )

    raw_type = item.get("type") or item.get("deviceTypeDisplayName")
    type_str = str(raw_type) if raw_type else None

    raw_caps = item.get("Capabilities") or ()
    caps: tuple[int, ...] = tuple(c for c in raw_caps if isinstance(c, int))

    return Device(
        id=device_id,
        label=str(item.get("label") or device_id),
        manufacturer=item.get("manufacturer"),
        model=item.get("model"),
        commands=tuple(dict.fromkeys(commands)),
        command_actions=command_actions,
        type=type_str,
        kind=_classify_device(type_str, item.get("manufacturer"), item.get("model")),
        command_groups=command_groups,
        power_features=_parse_power_features(item.get("powerFeatures")),
        is_manual_power=bool(item.get("isManualPower", False)),
        capabilities=caps,
        capability_labels=labels_for(caps),
    )


def _classify_device(
    raw_type: str | None,
    manufacturer: str | None,
    model: str | None,
) -> DeviceKind | None:
    if raw_type:
        lowered = raw_type.lower()
        if "television" in lowered or lowered == "tv":
            return "television"
        if "receiver" in lowered or "avr" in lowered or lowered == "audioavreceiver":
            return "avreceiver"
        if "speaker" in lowered or lowered == "soundbar":
            return "speaker"
        if "game" in lowered:
            return "game"
        if "stb" in lowered or "settop" in lowered or "cable" in lowered:
            return "stb"
    mfr = (manufacturer or "").lower()
    mdl = (model or "").lower()
    if "apple" in mfr and "tv" in mdl:
        return "appletv"
    if "sonos" in mfr:
        return "speaker"
    if raw_type:
        return "other"
    return None


def _parse_power_features(raw: Any) -> PowerFeatures | None:
    if not isinstance(raw, dict):
        return None
    on = _parse_power_actions(raw.get("PowerOnActions"))
    off = _parse_power_actions(raw.get("PowerOffActions"))
    if not on and not off:
        return None
    return PowerFeatures(on=on, off=off)


def _parse_power_actions(raw: Any) -> tuple[PowerAction, ...]:
    if not isinstance(raw, list):
        return ()
    actions: list[PowerAction] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cmd = entry.get("IRCommandName") or entry.get("command")
        if not cmd:
            continue
        order = entry.get("Order")
        duration = entry.get("Duration")
        actions.append(
            PowerAction(
                command=str(cmd),
                order=int(order) if isinstance(order, int) else 0,
                duration_ms=int(duration) if isinstance(duration, int) else None,
                action_type=entry.get("__type"),
            )
        )
    actions.sort(key=lambda a: a.order)
    return tuple(actions)


# ------------------------------------------------------------------ activity


def _parse_activity(item: dict[str, Any]) -> Activity | None:
    aid = str(item.get("id", ""))
    if not aid:
        return None

    roles_raw = item.get("roles") if isinstance(item.get("roles"), dict) else {}
    roles = ActivityRoles(
        volume_device_id=_coerce_id(
            roles_raw.get("VolumeActivityRole") or item.get("VolumeActivityRole")
        ),
        channel_device_id=_coerce_id(
            roles_raw.get("ChannelChangingActivityRole")
            or item.get("ChannelChangingActivityRole")
        ),
        display_device_id=_coerce_id(roles_raw.get("DisplayActivityRole")),
    )

    control_groups: dict[str, tuple[str, ...]] = {}
    for group in item.get("controlGroup") or []:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "Misc")
        funcs = group.get("function") or []
        commands = tuple(
            str(f.get("name")) for f in funcs if isinstance(f, dict) and f.get("name")
        )
        if commands:
            control_groups[name] = commands

    fixit = _parse_fixit(item.get("fixit"))

    order_raw = item.get("activityOrder")
    order = int(order_raw) if isinstance(order_raw, int) else None

    return Activity(
        id=aid,
        label=str(item.get("label") or aid),
        is_power_off=aid == _POWER_OFF_ID,
        type=str(item.get("type")) if item.get("type") else None,
        is_av_activity=bool(item.get("isAVActivity", False)),
        order=order,
        roles=roles,
        control_groups=control_groups,
        fixit=fixit,
    )


def _coerce_id(raw: Any) -> str | None:
    if raw in (None, "", "-1"):
        return None
    return str(raw)


def _parse_fixit(raw: Any) -> tuple[FixitState, ...]:
    if not isinstance(raw, dict):
        return ()
    states: list[FixitState] = []
    for device_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        states.append(
            FixitState(
                device_id=str(payload.get("id", device_id)),
                is_manual_power=bool(payload.get("isManualPower", False)),
                power=(
                    str(payload.get("Power"))
                    if payload.get("Power") is not None
                    else None
                ),
                raw=payload,
            )
        )
    return tuple(states)


# ------------------------------------------------------------------ sequence


def _parse_sequence(item: dict[str, Any]) -> Sequence | None:
    sid = str(item.get("id", ""))
    if not sid:
        return None
    actions: list[SequenceAction] = []
    for entry in item.get("sequence") or item.get("steps") or []:
        if not isinstance(entry, dict):
            continue
        actions.append(
            SequenceAction(
                command=(str(entry.get("command")) if entry.get("command") else None),
                device_id=(
                    str(entry.get("deviceId")) if entry.get("deviceId") else None
                ),
                delay_ms=(
                    int(entry["delay"]) if isinstance(entry.get("delay"), int) else None
                ),
                raw=entry,
            )
        )
    return Sequence(
        id=sid,
        label=str(item.get("label") or sid),
        actions=tuple(actions),
    )


# ------------------------------------------------------------------- content


def _parse_content(raw: Any) -> ContentEndpoints | None:
    if not isinstance(raw, dict):
        return None
    return ContentEndpoints(
        device_host=raw.get("contentDeviceHost"),
        image_host=raw.get("contentImageHost"),
        service_host=raw.get("contentServiceHost"),
        user_host=raw.get("contentUserHost"),
        household_user_profile_uri=raw.get("householdUserProfileUri"),
    )
