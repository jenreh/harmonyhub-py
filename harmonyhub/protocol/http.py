"""HTTP provisioning against the hub's port 8088 endpoint.

The hub answers a single discovery POST that exposes the ``activeRemoteId``
and the cloud ``discoveryServer`` domain. Both are needed to open the
WebSocket. The endpoint is local — no Logitech cloud round-trip is required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from harmonyhub.exceptions import HubUnavailableError, ProvisioningError

_LOG = logging.getLogger(__name__)

HUB_ORIGIN = "http://sl.dhg.myharmony.com"
HUB_PORT = 8088
_PROVISION_CMD = "setup.account?getProvisionInfo"
_SYNC_CMD = "setup.sync"


def _hub_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def _hub_headers() -> dict[str, str]:
    return {
        "Origin": HUB_ORIGIN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
    }


def _redact_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    keep = local[:2]
    return f"{keep}***@{domain}"


@dataclass(frozen=True)
class ProvisionInfo:
    remote_id: str
    discovery_server: str | None
    account_id: str | None
    email_redacted: str | None
    raw: dict[str, Any]


async def _post(
    host: str, command: str, *, port: int = HUB_PORT, timeout: float = 10.0
) -> dict[str, Any]:
    payload = {"id": 1, "cmd": command, "params": {}}
    url = _hub_url(host, port)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=_hub_headers(), json=payload)
    except httpx.ConnectError as exc:
        raise HubUnavailableError(
            f"Cannot connect to hub at {host}:{port}: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise HubUnavailableError(
            f"Timeout contacting hub at {host}:{port}: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise HubUnavailableError(
            f"HTTP error contacting hub at {host}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise ProvisioningError(
            f"Hub returned HTTP {response.status_code} for {command}: {response.text[:200]!r}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ProvisioningError(f"Hub returned non-JSON for {command}: {exc}") from exc


async def fetch_provision_info(
    host: str, *, port: int = HUB_PORT, timeout: float = 10.0
) -> ProvisionInfo:
    """Fetch provisioning info from the hub.

    Raises:
        HubUnavailableError: network-level failure (DNS, connect, timeout).
        ProvisioningError: hub responded but the payload is malformed or
            indicates a non-200 application status.
    """
    body = await _post(host, _PROVISION_CMD, port=port, timeout=timeout)
    if str(body.get("code", "200")) != "200":
        raise ProvisioningError(
            f"Hub returned application code {body.get('code')!r}: {body}"
        )
    data = body.get("data") or {}
    remote_id = data.get("activeRemoteId")
    if not remote_id:
        raise ProvisioningError("Provisioning response missing activeRemoteId")
    return ProvisionInfo(
        remote_id=str(remote_id),
        discovery_server=data.get("discoveryServer"),
        account_id=data.get("accountId"),
        email_redacted=_redact_email(data.get("email")),
        raw=data,
    )


async def post_sync(
    host: str, *, port: int = HUB_PORT, timeout: float = 10.0
) -> dict[str, Any]:
    """Trigger a hub-config sync. Useful after editing the hub from the app."""
    return await _post(host, _SYNC_CMD, port=port, timeout=timeout)
