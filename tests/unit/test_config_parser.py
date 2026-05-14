"""Tests for the hub-config parser."""

from __future__ import annotations

import json

from harmonyhub.client import _parse_config


def _func(name: str, ir_command: str, device_id: str = "1001") -> dict:
    return {
        "name": name,
        "label": name,
        "action": json.dumps(
            {"command": ir_command, "type": "IRCommand", "deviceId": device_id},
            separators=(",", ":"),
        ),
    }


def test_parses_activities_and_devices() -> None:
    raw = {
        "configVersion": 7,
        "activity": [
            {"id": "-1", "label": "PowerOff"},
            {"id": "100", "label": "Watch TV"},
        ],
        "device": [
            {
                "id": "1001",
                "label": "Denon AVR",
                "manufacturer": "Denon",
                "controlGroup": [
                    {
                        "function": [
                            _func("VolumeUp", "VolumeUp"),
                            _func("Mute", "Mute"),
                        ]
                    },
                ],
            },
        ],
    }
    config = _parse_config(raw)
    assert config.config_version == 7
    assert len(config.activities) == 2
    assert config.activities[0].is_power_off is True
    assert config.activities[1].label == "Watch TV"
    assert len(config.devices) == 1
    dev = config.devices[0]
    assert dev.commands == ("VolumeUp", "Mute")
    assert dev.command_actions == {"VolumeUp": "VolumeUp", "Mute": "Mute"}


def test_command_actions_translate_function_name_to_ir_command() -> None:
    raw = {
        "device": [
            {
                "id": "1002",
                "label": "Receiver",
                "controlGroup": [
                    {
                        "function": [
                            _func("Number1", "1", "1002"),
                            _func("Number2", "2", "1002"),
                        ]
                    },
                ],
            },
        ],
    }
    dev = _parse_config(raw).devices[0]
    assert dev.commands == ("Number1", "Number2")
    assert dev.command_actions["Number1"] == "1"
    assert dev.command_actions["Number2"] == "2"


def test_skips_malformed_function_entries() -> None:
    raw = {
        "device": [
            {
                "id": "1003",
                "label": "Quirky",
                "controlGroup": [
                    {
                        "function": [
                            _func("Good", "Good", "1003"),
                            {"name": "Bare"},
                            {"name": "BadAction", "action": "not-json"},
                            "not a dict",
                        ],
                    },
                ],
            },
        ],
    }
    dev = _parse_config(raw).devices[0]
    assert "Good" in dev.commands
    assert "Bare" in dev.commands
    assert "BadAction" in dev.commands
    assert dev.command_actions.get("Good") == "Good"
    # Bare and BadAction have no IR-command mapping → fallback to name.
    assert "Bare" not in dev.command_actions
    assert "BadAction" not in dev.command_actions


def test_dedupes_command_names() -> None:
    raw = {
        "device": [
            {
                "id": "1004",
                "label": "Dup",
                "controlGroup": [
                    {"function": [_func("A", "A", "1004"), _func("A", "A", "1004")]},
                ],
            },
        ],
    }
    dev = _parse_config(raw).devices[0]
    assert dev.commands == ("A",)
