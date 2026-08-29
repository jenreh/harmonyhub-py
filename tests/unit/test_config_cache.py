"""Config cache vs. hub configVersion on the state-digest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from harmonyhub.cache import read_json
from harmonyhub.client import _CMD_CONFIG, _CMD_STATE_DIGEST, HarmonyHubClient
from harmonyhub.protocol.http import ProvisionInfo

_HUB_CONFIG: dict[str, Any] = {
    "activity": [{"id": "100", "label": "Watch TV"}],
    "device": [],
}
_DIGEST_VERSION = 7


def _make_client() -> tuple[HarmonyHubClient, AsyncMock]:
    client = HarmonyHubClient("127.0.0.1")
    client._provision = ProvisionInfo(
        remote_id="hub-1",
        discovery_server="svcs.myharmony.com",
        account_id="acct",
        email_redacted="te***@example.com",
        raw={},
    )
    transport = AsyncMock()
    client._transport = transport
    return client, transport


def _request_side_effect(
    *,
    config: dict[str, Any] | None = None,
    digest: dict[str, Any] | None = None,
) -> Any:
    config_body = {"data": config if config is not None else dict(_HUB_CONFIG)}
    digest_body = (
        digest if digest is not None else {"data": {"configVersion": _DIGEST_VERSION}}
    )

    async def _request(cmd: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if cmd == _CMD_CONFIG:
            return config_body
        if cmd == _CMD_STATE_DIGEST:
            return digest_body
        raise AssertionError(f"unexpected command {cmd!r}")

    return _request


def _short(cmd: str) -> str:
    if "statedigest" in cmd:
        return "statedigest"
    if cmd.endswith("?config"):
        return "config"
    return cmd


def _pretty(payload: object) -> str:
    dumped = json.dumps(payload, indent=2, sort_keys=True)
    return "\n".join(f"    {line}" for line in dumped.splitlines())


async def test_second_get_config_reuses_cache_when_digest_version_matches(
    tmp_path: Path,
) -> None:
    assert "configVersion" not in _HUB_CONFIG

    client, transport = _make_client()
    transport.request.side_effect = _request_side_effect()

    with patch("harmonyhub.client.hub_cache_dir", return_value=tmp_path):
        await client.get_config()
        first_cmds = [_short(c.args[0]) for c in transport.request.await_args_list]
        cached = read_json(tmp_path / "config.json")

        client._config = None
        transport.request.reset_mock()
        await client.get_config()
        second_cmds = [_short(c.args[0]) for c in transport.request.await_args_list]

    if "config" in second_cmds:
        pytest.fail(
            "second get_config() pulled the full hub config again, even "
            "though the state-digest still reports an unchanged "
            f"configVersion={_DIGEST_VERSION}.\n"
            f"\n"
            f"  hub config payload keys: {sorted(_HUB_CONFIG)}\n"
            f"    (no configVersion — that field lives on the digest only)\n"
            f"\n"
            f"  cache file after first fetch:\n{_pretty(cached)}\n"
            f"\n"
            f"  1st get_config() commands: {first_cmds}\n"
            f"  2nd get_config() commands: {second_cmds}\n"
            f"  expected 2nd call:         ['statedigest']  (cache hit)\n"
            f"\n"
            f"  writer stores {{'data': <payload>}} with no digest version;\n"
            f"  reader looks up configVersion inside that payload, finds\n"
            f"  none, and treats the cache as unusable."
        )
