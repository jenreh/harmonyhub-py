"""Tests for runtime state persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from harmonyhub.status import RuntimeState, load_state, save_state, update_channel


def test_load_state_missing_returns_default(tmp_path: Path) -> None:
    with patch("harmonyhub.status.hub_cache_dir", return_value=tmp_path):
        state = load_state("hub-id")
    assert state == RuntimeState()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    with patch("harmonyhub.status.hub_cache_dir", return_value=tmp_path):
        save_state(
            "hub", RuntimeState(last_channel="42", last_channel_source="library")
        )
        loaded = load_state("hub")
    assert loaded.last_channel == "42"
    assert loaded.last_channel_source == "library"


def test_update_channel_preserves_other_fields() -> None:
    s = RuntimeState(last_channel="1", last_channel_source="library")
    updated = update_channel(s, "5", "harmony")
    assert updated.last_channel == "5"
    assert updated.last_channel_source == "harmony"
