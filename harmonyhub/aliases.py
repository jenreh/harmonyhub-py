"""Logical-key → Harmony IR command resolver with fallback chains.

A logical key (e.g. ``volume_up``) maps to an ordered list of candidate command
names. Different manufacturers use different names for the same physical button;
the resolver picks the first candidate present on the device.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from harmonyhub.exceptions import CommandNotFoundError
from harmonyhub.models import LogicalKey

ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "volume_up": ("VolumeUp", "VolUp", "Volume+"),
    "volume_down": ("VolumeDown", "VolDown", "Volume-"),
    "mute": ("Mute", "MuteToggle", "VolumeMute"),
    "channel_up": ("ChannelUp", "Channel+", "ProgramUp", "ChannelNext"),
    "channel_down": ("ChannelDown", "Channel-", "ProgramDown", "ChannelPrev"),
    "ok": ("OK", "Enter", "Select", "DirectionSelect"),
    "enter": ("Enter", "OK", "Select", "DirectionSelect"),
    "back": ("Back", "Return", "Exit", "PreviousMenu", "DirectionBack"),
    "power_on": ("PowerOn",),
    "power_on_fallback": ("PowerOn", "PowerToggle"),
    "power_off": ("PowerOff",),
}

for _digit in range(10):
    ALIASES[f"digit_{_digit}"] = (
        str(_digit),
        f"Number{_digit}",
        f"Digit{_digit}",
        f"Num{_digit}",
    )


def candidates_for(key: LogicalKey | str) -> tuple[str, ...]:
    """Return the candidate command list for a logical key."""
    return ALIASES.get(key, ())


def resolve(
    key: LogicalKey | str,
    available_commands: Iterable[str],
    *,
    device_label: str = "<unknown>",
) -> str:
    """Pick the first alias candidate present on the device.

    Raises:
        CommandNotFoundError: if neither the logical-key candidates nor the
            raw key name match an available command.
    """
    available = set(available_commands)
    for candidate in candidates_for(key):
        if candidate in available:
            return candidate
    if key in available:
        return str(key)
    raise CommandNotFoundError(str(key), device_label, available=sorted(available))
