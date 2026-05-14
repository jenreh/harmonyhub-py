"""Tests for HTTP provisioning."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from harmonyhub.exceptions import HubUnavailableError, ProvisioningError
from harmonyhub.protocol.http import fetch_provision_info


async def test_fetch_provision_info_happy(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://hub.local:8088/",
        json={
            "data": {
                "activeRemoteId": "12345678",
                "accountId": "acct",
                "email": "user@example.com",
                "discoveryServer": "https://svcs.myharmony.com/Discovery/Discovery.svc",
                "friendlyName": "Wohnzimmer",
                "currentFwVersion": "4.15.250",
            },
            "code": "200",
        },
    )
    info = await fetch_provision_info("hub.local")
    assert info.remote_id == "12345678"
    assert info.account_id == "acct"
    assert info.discovery_server.endswith("Discovery.svc")
    assert info.email_redacted == "us***@example.com"


async def test_fetch_provision_info_redacts_email(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://hub.local:8088/",
        json={
            "data": {"activeRemoteId": "1", "email": "abcdef@example.com"},
            "code": "200",
        },
    )
    info = await fetch_provision_info("hub.local")
    assert info.email_redacted == "ab***@example.com"


async def test_fetch_provision_info_raises_on_404_code(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://hub.local:8088/",
        json={"code": "404"},
    )
    with pytest.raises(ProvisioningError):
        await fetch_provision_info("hub.local")


async def test_fetch_provision_info_unavailable_on_http_error(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_exception(Exception("boom"))
    with pytest.raises((HubUnavailableError, ProvisioningError, Exception)):
        await fetch_provision_info("hub.local")
