"""Tests for the frozen dataclass model layer."""

from __future__ import annotations

import pytest

from harmonyhub.models import Activity, Device, HubInfo


def test_models_are_frozen() -> None:
    info = HubInfo(host="x", remote_id="1")
    with pytest.raises(Exception):  # FrozenInstanceError / AttributeError
        info.host = "y"  # type: ignore[misc]


def test_device_default_command_actions_is_independent() -> None:
    a = Device(id="1", label="A", manufacturer=None, model=None, commands=())
    b = Device(id="2", label="B", manufacturer=None, model=None, commands=())
    a.command_actions["x"] = "y"
    assert "x" not in b.command_actions


def test_activity_power_off_flag() -> None:
    off = Activity(id="-1", label="PowerOff", is_power_off=True)
    on = Activity(id="100", label="Watch TV")
    assert off.is_power_off
    assert not on.is_power_off
