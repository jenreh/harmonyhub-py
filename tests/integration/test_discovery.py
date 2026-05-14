"""Integration tests for Harmony Hub discovery using FakeHub simulator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harmonyhub.discovery import discover
from harmonyhub.simulator import FakeHub


@pytest.mark.asyncio
async def test_discover_with_fake_hub(fake_hub: FakeHub) -> None:
    """Discovery can find and provision a simulated FakeHub."""
    # Mock mDNS to report the FakeHub
    with patch("harmonyhub.discovery.AsyncZeroconf") as mock_azc_class:
        mock_azc = MagicMock()
        mock_azc_class.return_value = mock_azc
        mock_azc.async_close = __import__("asyncio").coroutine(lambda: None)()

        # Create mock service info for FakeHub
        service_info = MagicMock()
        service_info.addresses.return_value = [
            __import__("ipaddress").IPv4Address(fake_hub.host).packed
        ]
        service_info.name = f"{fake_hub.friendly_name}._hap._tcp.local."

        mock_azc.zeroconf.get_service_info = MagicMock(return_value=service_info)

        # Mock ServiceBrowser to report the service
        def mock_service_browser(zc, service_type, listener):
            listener.add_service(
                zc, service_type, f"{fake_hub.friendly_name}._hap._tcp.local."
            )

        with patch(
            "harmonyhub.discovery.ServiceBrowser", side_effect=mock_service_browser
        ):
            hubs = []
            async for hub in discover(timeout=0.1):
                hubs.append(hub)

            assert len(hubs) == 1
            assert hubs[0].host == fake_hub.host
            assert hubs[0].remote_id == fake_hub.remote_id
            assert hubs[0].friendly_name == fake_hub.friendly_name
