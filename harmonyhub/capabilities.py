"""Decode Logitech Harmony device-capability integer codes.

The hub publishes a ``Capabilities`` list on each device (e.g. ``[1, 2, 3, 5, 8]``).
Logitech never published a public mapping; the values below are derived from
community reverse-engineering. Unknown codes are kept as their integer form.
"""

from __future__ import annotations

from typing import Final

_CAPABILITY_NAMES: Final[dict[int, str]] = {
    1: "Power",
    2: "Volume",
    3: "ChannelChange",
    5: "Numeric",
    8: "Transport",
    9: "NavigationBasic",
    10: "TransportRecording",
    11: "TransportExtended",
    13: "NavigationExtended",
    24: "ColoredButtons",
    25: "PictureAdjustment",
    47: "GoogleTVNavigation",
    49: "SoundModes",
}


def label_for(code: int) -> str:
    """Return a human-readable label for a capability code, or its raw int."""
    return _CAPABILITY_NAMES.get(code, str(code))


def labels_for(codes: tuple[int, ...]) -> tuple[str, ...]:
    """Map a tuple of capability codes to a tuple of human-readable labels."""
    return tuple(label_for(c) for c in codes)
