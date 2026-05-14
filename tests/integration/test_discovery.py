"""Integration tests for Harmony Hub discovery using FakeHub simulator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from harmonyhub.discovery import DiscoveredHub, discover
from harmonyhub.simulator import FakeHub


@pytest.mark.asyncio
async def test_discover_with_fake_hub(fake_hub: FakeHub) -> None:
    """Discovery finds and provisions a FakeHub via simulated subnet scan."""
    location = f"http://{fake_hub.host}:8088/description.xml"
    prov = fake_hub.provision_info

    with (
        # No SSDP responses in test environment
        patch("harmonyhub.discovery._ssdp_search", new_callable=AsyncMock) as mock_ssdp,
        # Subnet scan returns the FakeHub's description URL
        patch("harmonyhub.discovery._subnet_scan", new_callable=AsyncMock) as mock_scan,
        patch("harmonyhub.discovery._get_local_ip", return_value=fake_hub.host),
        # FakeHub has no HTTP server; return synthetic provision info
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
        # Return friendly name from FakeHub's raw provision data
        patch(
            "harmonyhub.discovery._fetch_friendly_name", new_callable=AsyncMock
        ) as mock_name,
    ):
        mock_ssdp.return_value = []
        mock_scan.return_value = [location]
        mock_prov.return_value = prov
        mock_name.return_value = prov.raw["friendlyName"]

        hubs: list[DiscoveredHub] = []
        async for hub in discover(timeout=2.0):
            hubs.append(hub)

    assert len(hubs) == 1
    assert hubs[0].host == fake_hub.host
    assert hubs[0].remote_id == prov.remote_id
    assert hubs[0].friendly_name == prov.raw["friendlyName"]
