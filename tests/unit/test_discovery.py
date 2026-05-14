"""Unit tests for Harmony Hub discovery (SSDP + subnet scan)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harmonyhub.discovery import (
    DiscoveredHub,
    _fetch_friendly_name,
    _is_harmony_hub,
    _provision_hub,
    _ssdp_search,
    discover,
)
from harmonyhub.exceptions import HubUnavailableError, ProvisioningError
from harmonyhub.protocol.http import ProvisionInfo

# ---------------------------------------------------------------------------
# _ssdp_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ssdp_search_no_responses() -> None:
    """Returns empty list when no SSDP responses arrive."""
    with patch("harmonyhub.discovery.asyncio.get_running_loop") as mock_loop_fn:
        mock_loop = MagicMock()
        mock_loop_fn.return_value = mock_loop

        async def _wait_for(coro, timeout):
            raise TimeoutError

        mock_loop.time.side_effect = [0.0, 0.0, 0.2]  # deadline exceeded quickly
        mock_transport = MagicMock()
        mock_loop.create_datagram_endpoint = AsyncMock(
            return_value=(mock_transport, None)
        )
        with patch("harmonyhub.discovery.asyncio.wait_for", side_effect=TimeoutError):
            result = await _ssdp_search(0.1)
    assert result == []


@pytest.mark.asyncio
async def test_ssdp_search_extracts_location() -> None:
    """Extracts LOCATION header from SSDP response via regex."""
    from harmonyhub.discovery import _RE_LOCATION

    ssdp_response = (
        "HTTP/1.1 200 OK\r\n"
        "CACHE-CONTROL: max-age=1800\r\n"
        "LOCATION: http://192.168.1.100:8088/description.xml\r\n"
        "ST: urn:myharmony-com:device:harmony:1\r\n"
        "\r\n"
    )
    match = _RE_LOCATION.search(ssdp_response)
    assert match is not None
    assert match.group(1).strip() == "http://192.168.1.100:8088/description.xml"


# ---------------------------------------------------------------------------
# _is_harmony_hub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_harmony_hub_match() -> None:
    """Returns description URL when device type matches."""
    mock_resp = MagicMock()
    mock_resp.text = (
        "<deviceType>urn:myharmony-com:device:harmony:1</deviceType>"
        "<friendlyName>Harmony Hub</friendlyName>"
    )

    with patch("harmonyhub.discovery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _is_harmony_hub("192.168.1.100")

    assert result == "http://192.168.1.100:8088/description.xml"


@pytest.mark.asyncio
async def test_is_harmony_hub_mismatch() -> None:
    """Returns None when device type does not match."""
    mock_resp = MagicMock()
    mock_resp.text = "<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>"

    with patch("harmonyhub.discovery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _is_harmony_hub("192.168.1.1")

    assert result is None


@pytest.mark.asyncio
async def test_is_harmony_hub_network_error() -> None:
    """Returns None when HTTP request fails."""
    with patch("harmonyhub.discovery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=OSError("connection refused"))

        result = await _is_harmony_hub("192.168.1.200")

    assert result is None


# ---------------------------------------------------------------------------
# _fetch_friendly_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_friendly_name_success() -> None:
    """Extracts friendlyName from description XML."""
    mock_resp = MagicMock()
    mock_resp.text = "<friendlyName>My Harmony</friendlyName>"

    with patch("harmonyhub.discovery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _fetch_friendly_name("http://192.168.1.100:8088/description.xml")

    assert result == "My Harmony"


@pytest.mark.asyncio
async def test_fetch_friendly_name_missing() -> None:
    """Returns None when friendlyName tag is absent."""
    mock_resp = MagicMock()
    mock_resp.text = "<device><manufacturer>Logitech</manufacturer></device>"

    with patch("harmonyhub.discovery.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _fetch_friendly_name("http://192.168.1.100:8088/description.xml")

    assert result is None


# ---------------------------------------------------------------------------
# _provision_hub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_hub_success() -> None:
    """Returns DiscoveredHub with provisioning data."""
    prov = ProvisionInfo(
        remote_id="12345678",
        discovery_server="discovery.logitech.com",
        account_id="acc1",
        email_redacted="u***@e.com",
        raw={},
    )

    with (
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
        patch(
            "harmonyhub.discovery._fetch_friendly_name", new_callable=AsyncMock
        ) as mock_name,
    ):
        mock_prov.return_value = prov
        mock_name.return_value = "Living Room Hub"

        result = await _provision_hub("http://192.168.1.100:8088/description.xml")

    assert isinstance(result, DiscoveredHub)
    assert result.host == "192.168.1.100"
    assert result.remote_id == "12345678"
    assert result.friendly_name == "Living Room Hub"


@pytest.mark.asyncio
async def test_provision_hub_unavailable() -> None:
    """Returns DiscoveredHub with None remote_id when hub is unavailable."""
    with (
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
    ):
        mock_prov.side_effect = HubUnavailableError("unreachable")

        result = await _provision_hub("http://192.168.1.100:8088/description.xml")

    assert isinstance(result, DiscoveredHub)
    assert result.host == "192.168.1.100"
    assert result.remote_id is None


@pytest.mark.asyncio
async def test_provision_hub_provisioning_error() -> None:
    """Returns DiscoveredHub with None remote_id on ProvisioningError."""
    with (
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
    ):
        mock_prov.side_effect = ProvisioningError("bad response")

        result = await _provision_hub("http://192.168.1.100:8088/description.xml")

    assert isinstance(result, DiscoveredHub)
    assert result.remote_id is None


@pytest.mark.asyncio
async def test_provision_hub_bad_url() -> None:
    """Returns None when location URL has no parseable host."""
    result = await _provision_hub("not-a-url")
    assert result is None


# ---------------------------------------------------------------------------
# discover (integration of all pieces)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_no_hubs() -> None:
    """Yields nothing when no hubs are found on the network."""
    with (
        patch("harmonyhub.discovery._ssdp_search", new_callable=AsyncMock) as mock_ssdp,
        patch("harmonyhub.discovery._subnet_scan", new_callable=AsyncMock) as mock_scan,
        patch("harmonyhub.discovery._get_local_ip", return_value="192.168.1.10"),
    ):
        mock_ssdp.return_value = []
        mock_scan.return_value = []

        hubs = [hub async for hub in discover(timeout=1.0)]

    assert hubs == []


@pytest.mark.asyncio
async def test_discover_single_hub_via_scan() -> None:
    """Yields one hub discovered via subnet scan."""
    location = "http://192.168.1.100:8088/description.xml"
    prov = ProvisionInfo(
        remote_id="99998888",
        discovery_server="disc.logitech.com",
        account_id="acc2",
        email_redacted="x***@y.com",
        raw={},
    )

    with (
        patch("harmonyhub.discovery._ssdp_search", new_callable=AsyncMock) as mock_ssdp,
        patch("harmonyhub.discovery._subnet_scan", new_callable=AsyncMock) as mock_scan,
        patch("harmonyhub.discovery._get_local_ip", return_value="192.168.1.10"),
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
        patch(
            "harmonyhub.discovery._fetch_friendly_name", new_callable=AsyncMock
        ) as mock_name,
    ):
        mock_ssdp.return_value = []
        mock_scan.return_value = [location]
        mock_prov.return_value = prov
        mock_name.return_value = "My Hub"

        hubs = [hub async for hub in discover(timeout=5.0)]

    assert len(hubs) == 1
    assert hubs[0].host == "192.168.1.100"
    assert hubs[0].remote_id == "99998888"
    assert hubs[0].friendly_name == "My Hub"


@pytest.mark.asyncio
async def test_discover_deduplicates_ssdp_and_scan() -> None:
    """Hub found via both SSDP and scan is returned only once."""
    location = "http://192.168.1.100:8088/description.xml"
    prov = ProvisionInfo(
        remote_id="11112222",
        discovery_server="x",
        account_id="y",
        email_redacted="z",
        raw={},
    )

    with (
        patch("harmonyhub.discovery._ssdp_search", new_callable=AsyncMock) as mock_ssdp,
        patch("harmonyhub.discovery._subnet_scan", new_callable=AsyncMock) as mock_scan,
        patch("harmonyhub.discovery._get_local_ip", return_value="192.168.1.10"),
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
        patch(
            "harmonyhub.discovery._fetch_friendly_name", new_callable=AsyncMock
        ) as mock_name,
    ):
        mock_ssdp.return_value = [location]
        mock_scan.return_value = [location]  # same location → deduplicated
        mock_prov.return_value = prov
        mock_name.return_value = "Hub"

        hubs = [hub async for hub in discover(timeout=5.0)]

    assert len(hubs) == 1


@pytest.mark.asyncio
async def test_discover_local_ip_failure() -> None:
    """Falls back to SSDP-only when local IP cannot be determined."""
    location = "http://10.0.0.5:8088/description.xml"
    prov = ProvisionInfo(
        remote_id="55556666",
        discovery_server="x",
        account_id="y",
        email_redacted="z",
        raw={},
    )

    with (
        patch("harmonyhub.discovery._ssdp_search", new_callable=AsyncMock) as mock_ssdp,
        patch("harmonyhub.discovery._get_local_ip", side_effect=OSError("no route")),
        patch(
            "harmonyhub.discovery.fetch_provision_info", new_callable=AsyncMock
        ) as mock_prov,
        patch(
            "harmonyhub.discovery._fetch_friendly_name", new_callable=AsyncMock
        ) as mock_name,
    ):
        mock_ssdp.return_value = [location]
        mock_prov.return_value = prov
        mock_name.return_value = "Office Hub"

        hubs = [hub async for hub in discover(timeout=3.0)]

    assert len(hubs) == 1
    assert hubs[0].host == "10.0.0.5"
