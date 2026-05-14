"""Runtime state persistence (last_channel + its provenance).

The hub itself has no notion of the current channel. We track it locally and
flag the source so callers can tell whether the value is library-tracked or
just an old cached value of unknown freshness.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from harmonyhub.cache import hub_cache_dir, read_json, write_json

ChannelSource = Literal["library", "harmony", "unknown"]


@dataclass(frozen=True, slots=True)
class RuntimeState:
    last_channel: str | None = None
    last_channel_source: ChannelSource = "unknown"


def _state_path(hub_id: str):
    return hub_cache_dir(hub_id) / "state.json"


def load_state(hub_id: str) -> RuntimeState:
    payload = read_json(_state_path(hub_id))
    if not payload:
        return RuntimeState()
    source = payload.get("last_channel_source", "unknown")
    if source not in ("library", "harmony", "unknown"):
        source = "unknown"
    return RuntimeState(
        last_channel=payload.get("last_channel"),
        last_channel_source=source,
    )


def save_state(hub_id: str, state: RuntimeState) -> None:
    write_json(
        _state_path(hub_id),
        {
            "last_channel": state.last_channel,
            "last_channel_source": state.last_channel_source,
        },
    )


def update_channel(
    state: RuntimeState, channel: str, source: ChannelSource
) -> RuntimeState:
    return replace(state, last_channel=channel, last_channel_source=source)
