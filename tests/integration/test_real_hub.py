"""Opt-in integration test against a real hub.

Run with::

    HARMONY_HUB_HOST=192.168.x.x pytest -m integration

Skipped automatically when the env var is unset.
"""

from __future__ import annotations

import os

import pytest

from harmonyhub import HarmonyHubClient

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.environ.get("HARMONY_HUB_HOST"), reason="no real hub configured"
)
async def test_real_hub_info_and_config() -> None:
    host = os.environ["HARMONY_HUB_HOST"]
    async with HarmonyHubClient(host) as hub:
        info = await hub.get_info()
        assert info.remote_id
        cfg = await hub.get_config()
        assert cfg.activities, "hub should have at least one activity"
        assert cfg.devices, "hub should have at least one device"
