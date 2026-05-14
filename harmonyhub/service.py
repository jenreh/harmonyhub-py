from __future__ import annotations

import os
import types
from dataclasses import asdict, is_dataclass
from typing import Any

from harmonyhub.client import HarmonyHubClient
from harmonyhub.config import load as load_app_config
from harmonyhub.exceptions import HarmonyHubError


def resolve_host(host: str | None = None) -> str:
    if host:
        return host
    cfg = load_app_config()
    res = os.environ.get("HARMONY_HUB_HOST") or cfg.host
    if not res:
        raise HarmonyHubError(
            "No hub host configured. Set HARMONY_HUB_HOST or [hub].host in config.toml."
        )
    return res


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


class HarmonyService:
    """Service class for Harmony Hub providing high-level reusable logic."""

    def __init__(
        self, host: str | None = None, connection_mode: str = "ondemand"
    ) -> None:
        self.host = resolve_host(host)
        self.client = HarmonyHubClient(self.host, connection_mode=connection_mode)

    async def __aenter__(self) -> HarmonyService:
        await self.client.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.client.close()

    async def connect(self) -> None:
        await self.client.connect()

    async def close(self) -> None:
        await self.client.close()
