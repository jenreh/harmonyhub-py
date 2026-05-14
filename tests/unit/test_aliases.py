"""Tests for the logical-key alias resolver."""

from __future__ import annotations

import pytest

from harmonyhub import aliases
from harmonyhub.exceptions import CommandNotFoundError


def test_resolve_picks_first_present() -> None:
    available = ["VolumeUp", "VolumeDown"]
    assert aliases.resolve("volume_up", available) == "VolumeUp"


def test_resolve_falls_back_through_chain() -> None:
    # Primary "VolumeUp" missing; fallback "Volume+" present.
    available = ["Volume+", "Mute"]
    assert aliases.resolve("volume_up", available) == "Volume+"


def test_resolve_digits() -> None:
    assert aliases.resolve("digit_1", ["Number1"]) == "Number1"
    assert aliases.resolve("digit_5", ["5"]) == "5"


def test_resolve_raw_key_passes_through() -> None:
    assert aliases.resolve("CustomCmd", ["CustomCmd"]) == "CustomCmd"


def test_resolve_raises_when_missing() -> None:
    with pytest.raises(CommandNotFoundError):
        aliases.resolve("volume_up", ["Mute", "Power"])


def test_mute_alias_present() -> None:
    assert aliases.resolve("mute", ["Mute"]) == "Mute"
    assert aliases.resolve("mute", ["MuteToggle"]) == "MuteToggle"


def test_candidates_for_unknown_returns_empty() -> None:
    assert aliases.candidates_for("not_a_key") == ()
