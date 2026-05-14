"""Schema snapshot test against the real ``harmony_config.json``.

Loads the on-disk hub payload from the repository root and asserts that the
parser extracts every P1/P2/P3 field documented in the implementation plan.
Guards against silent regressions in :mod:`harmonyhub.parser`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harmonyhub.models import HubConfig
from harmonyhub.parser import parse_config

_FIXTURE = Path(__file__).resolve().parents[2] / "harmony_config.json"


@pytest.fixture(scope="module")
def hub_config() -> HubConfig:
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture {_FIXTURE} not present")
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return parse_config(data)


def test_counts(hub_config: HubConfig) -> None:
    assert len(hub_config.devices) == 5
    assert len(hub_config.activities) == 5


def test_locale_and_content(hub_config: HubConfig) -> None:
    assert hub_config.locale == "en-US"
    assert hub_config.content is not None
    assert hub_config.content.image_host is not None
    assert "{stationId}" in hub_config.content.image_host


def test_device_kinds(hub_config: HubConfig) -> None:
    by_id = {d.id: d for d in hub_config.devices}
    assert by_id["78652298"].kind == "television"
    assert by_id["78652295"].kind == "avreceiver"
    assert by_id["78652294"].kind == "appletv"
    assert by_id["78652296"].kind == "speaker"
    assert by_id["78652297"].kind == "speaker"


def test_device_command_groups(hub_config: HubConfig) -> None:
    tv = next(d for d in hub_config.devices if d.id == "78652298")
    assert "Power" in tv.command_groups
    assert "Volume" in tv.command_groups
    assert "PowerOn" in tv.command_groups["Power"]
    assert "PowerOff" in tv.command_groups["Power"]


def test_device_power_features(hub_config: HubConfig) -> None:
    yamaha = next(d for d in hub_config.devices if d.id == "78652295")
    assert yamaha.power_features is not None
    assert yamaha.power_features.on
    assert yamaha.power_features.on[0].command == "PowerOn"
    assert yamaha.power_features.off[0].command == "PowerOff"


def test_device_capabilities(hub_config: HubConfig) -> None:
    tv = next(d for d in hub_config.devices if d.id == "78652298")
    assert tv.capabilities  # non-empty
    assert "Power" in tv.capability_labels


def test_activity_roles(hub_config: HubConfig) -> None:
    fernsehen = next(a for a in hub_config.activities if a.label == "Fernsehen")
    assert fernsehen.roles.volume_device_id == "78652295"
    assert fernsehen.roles.channel_device_id == "78652298"
    assert fernsehen.roles.display_device_id == "78652298"
    assert fernsehen.type == "VirtualTelevisionN"
    assert fernsehen.is_av_activity is True


def test_activity_control_groups_non_empty(hub_config: HubConfig) -> None:
    fernsehen = next(a for a in hub_config.activities if a.label == "Fernsehen")
    assert "Volume" in fernsehen.control_groups
    channel = fernsehen.control_groups.get("Channel", ())
    assert "ChannelPrev" in channel or "ChannelDown" in channel


def test_power_off_activity_flag(hub_config: HubConfig) -> None:
    off = next(a for a in hub_config.activities if a.is_power_off)
    assert off.id == "-1"
    assert off.label == "PowerOff"


def test_fixit_present(hub_config: HubConfig) -> None:
    fernsehen = next(a for a in hub_config.activities if a.label == "Fernsehen")
    assert fernsehen.fixit  # non-empty
    by_id = {f.device_id: f for f in fernsehen.fixit}
    assert "78652294" in by_id
