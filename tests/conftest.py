"""Shared fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from harmonyhub.simulator import FakeHub


@pytest.fixture
async def fake_hub() -> AsyncIterator[FakeHub]:
    async with FakeHub() as hub:
        yield hub


def real_hub_host() -> str | None:
    return os.environ.get("HARMONY_HUB_HOST")
