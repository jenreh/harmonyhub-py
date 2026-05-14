"""Hub discovery via SSDP M-SEARCH and subnet port scan.

Harmony Hubs serve a UPnP description document at ``http://<host>:8088/description.xml``
with device type ``urn:myharmony-com:device:harmony:1``. This module uses two
complementary strategies:

1. **SSDP M-SEARCH** (active, ~3 s): multicast query to 239.255.255.250:1900.
   Works for hubs that respond to UPnP M-SEARCH. Yields quick results on
   compliant implementations.

2. **Subnet port scan** (parallel TCP, <1 s): probes all hosts on the /24 subnet
   for port 8088, then verifies the UPnP device type. Reliable fallback for hubs
   that silently ignore M-SEARCH (most current Harmony Hub firmware).

Note: ``_logitech-reverse-bonjour._tcp.local.`` is a *reverse* mDNS mechanism —
the *hub* browses for the app (not the other way around). It is not used here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from harmonyhub.exceptions import HubUnavailableError, ProvisioningError
from harmonyhub.protocol.http import fetch_provision_info

_LOG = logging.getLogger(__name__)

_SSDP_ADDR = "239.255.255.250"
_SSDP_PORT = 1900
_SSDP_ST = "urn:myharmony-com:device:harmony:1"
_HUB_PORT = 8088
_HARMONY_DEVICE_TYPE = "urn:myharmony-com:device:harmony:1"

_M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    f"ST: {_SSDP_ST}\r\n"
    "\r\n"
)

_RE_LOCATION = re.compile(r"(?i)^LOCATION:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class DiscoveredHub:
    host: str
    remote_id: str | None
    friendly_name: str | None


# ---------------------------------------------------------------------------
# SSDP helpers
# ---------------------------------------------------------------------------


class _SsdpProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol that collects SSDP response packets."""

    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        self._queue.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        _LOG.debug("SSDP socket error: %s", exc)


async def _ssdp_search(timeout: float) -> list[str]:
    """Send an SSDP M-SEARCH and collect LOCATION URLs from responses.

    Args:
        timeout: Seconds to wait for SSDP responses.

    Returns:
        List of unique LOCATION URLs from responding devices.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _SsdpProtocol(queue),
        family=socket.AF_INET,
        allow_broadcast=True,
    )

    try:
        transport.sendto(_M_SEARCH.encode(), (_SSDP_ADDR, _SSDP_PORT))
        _LOG.debug("Sent SSDP M-SEARCH for %s", _SSDP_ST)

        locations: set[str] = set()
        deadline = loop.time() + timeout

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=remaining)
                text = data.decode(errors="replace")
                match = _RE_LOCATION.search(text)
                if match:
                    location = match.group(1).strip()
                    _LOG.debug("SSDP response LOCATION: %s", location)
                    locations.add(location)
            except TimeoutError:
                break
    finally:
        transport.close()

    return list(locations)


# ---------------------------------------------------------------------------
# Subnet scan helpers
# ---------------------------------------------------------------------------


def _get_local_ip() -> str:
    """Return the primary local IPv4 address by routing toward a public host."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


async def _tcp_reachable(host: str, port: int, timeout: float) -> bool:
    """Return True if ``host:port`` accepts a TCP connection within *timeout*."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False


async def _is_harmony_hub(host: str, *, timeout: float = 2.0) -> str | None:
    """Fetch the UPnP description and confirm this is a Harmony Hub.

    Args:
        host: IP address to probe.
        timeout: HTTP request timeout.

    Returns:
        The description URL if the host is a Harmony Hub, else ``None``.
    """
    url = f"http://{host}:{_HUB_PORT}/description.xml"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        if _HARMONY_DEVICE_TYPE in resp.text:
            _LOG.debug("Confirmed Harmony Hub at %s via description.xml", host)
            return url
    except Exception as exc:
        _LOG.debug("No Harmony Hub at %s: %s", host, exc)
    return None


async def _subnet_scan(local_ip: str, *, connect_timeout: float = 0.4) -> list[str]:
    """Scan the /24 subnet for Harmony Hubs on port 8088.

    Two-phase approach:
    1. TCP connection probe (fast, low overhead)
    2. Device-type verification via description.xml

    Args:
        local_ip: Local IPv4 address used to determine the /24 subnet.
        connect_timeout: TCP connect timeout per host.

    Returns:
        List of UPnP description URLs for discovered Harmony Hubs.
    """
    network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    all_hosts = [str(h) for h in network.hosts()]

    _LOG.debug(
        "Scanning %d hosts on %s for port %d", len(all_hosts), network, _HUB_PORT
    )

    tcp_results = await asyncio.gather(
        *[_tcp_reachable(h, _HUB_PORT, connect_timeout) for h in all_hosts],
        return_exceptions=True,
    )
    reachable = [h for h, ok in zip(all_hosts, tcp_results, strict=True) if ok is True]

    _LOG.debug(
        "Subnet scan: %d/%d host(s) have port %d open",
        len(reachable),
        len(all_hosts),
        _HUB_PORT,
    )

    if not reachable:
        return []

    verify_results = await asyncio.gather(
        *[_is_harmony_hub(h) for h in reachable],
        return_exceptions=True,
    )
    return [r for r in verify_results if isinstance(r, str)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def discover(*, timeout: float = 30.0) -> AsyncIterator[DiscoveredHub]:
    """Discover Harmony Hubs on the local network.

    Uses SSDP M-SEARCH and subnet port scan in parallel.  Most current Harmony
    Hub firmware silently ignores M-SEARCH; the port scan is the reliable path.

    Args:
        timeout: Total discovery budget in seconds.

    Yields:
        DiscoveredHub: Each discovered hub with host, remote_id, and friendly_name.
    """
    _LOG.debug("Starting discovery with timeout %.1f seconds", timeout)

    ssdp_timeout = min(3.0, timeout * 0.15)

    try:
        local_ip = _get_local_ip()
    except OSError as exc:
        _LOG.warning("Cannot determine local IP: %s", exc)
        local_ip = None

    # Run SSDP and subnet scan concurrently
    scan_tasks: list[asyncio.Task[list[str]]] = []
    scan_tasks.append(asyncio.create_task(_ssdp_search(ssdp_timeout)))
    if local_ip:
        connect_timeout = min(0.5, (timeout - ssdp_timeout) / 10)
        scan_tasks.append(
            asyncio.create_task(_subnet_scan(local_ip, connect_timeout=connect_timeout))
        )

    gathered = await asyncio.gather(*scan_tasks, return_exceptions=True)

    all_locations: dict[str, None] = {}
    for result in gathered:
        if isinstance(result, list):
            for loc in result:
                all_locations[loc] = None

    _LOG.debug("Discovery found %d unique location(s)", len(all_locations))

    if not all_locations:
        return

    provision_results = await asyncio.gather(
        *[_provision_hub(loc) for loc in all_locations],
        return_exceptions=True,
    )

    for result in provision_results:
        if isinstance(result, DiscoveredHub):
            _LOG.info(
                "Discovered hub: host=%s remote_id=%s friendly_name=%s",
                result.host,
                result.remote_id,
                result.friendly_name,
            )
            yield result
        elif isinstance(result, Exception):
            _LOG.debug("Hub provisioning failed: %s", result)


async def _provision_hub(location_url: str) -> DiscoveredHub | None:
    """Provision a hub found via SSDP or subnet scan.

    Fetches remote ID via HTTP provisioning and friendly name from the UPnP
    description XML.

    Args:
        location_url: URL of the hub's UPnP description document.

    Returns:
        DiscoveredHub on success, None if the host cannot be determined.
    """
    parsed = urlparse(location_url)
    host = parsed.hostname
    if not host:
        _LOG.warning("Cannot extract host from LOCATION: %s", location_url)
        return None

    _LOG.debug("Provisioning hub at %s", host)

    friendly_name_task = asyncio.create_task(_fetch_friendly_name(location_url))

    try:
        prov_info = await fetch_provision_info(host, port=_HUB_PORT, timeout=3.0)
        remote_id = prov_info.remote_id
    except (HubUnavailableError, ProvisioningError) as exc:
        _LOG.debug("Provisioning failed for %s: %s", host, exc)
        friendly_name_task.cancel()
        return DiscoveredHub(host=host, remote_id=None, friendly_name=None)

    friendly_name = await friendly_name_task
    return DiscoveredHub(host=host, remote_id=remote_id, friendly_name=friendly_name)


async def _fetch_friendly_name(location_url: str) -> str | None:
    """Fetch the UPnP description XML and extract ``<friendlyName>``.

    Args:
        location_url: URL of the UPnP description document.

    Returns:
        The friendly name string, or ``None`` if not found.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(location_url)
        match = re.search(r"<friendlyName>([^<]+)</friendlyName>", resp.text)
        if match:
            return match.group(1).strip()
    except Exception as exc:
        _LOG.debug("Failed to fetch device description from %s: %s", location_url, exc)
    return None
