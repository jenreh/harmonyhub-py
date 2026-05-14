"""Error hierarchy for the harmonyhub library."""

from __future__ import annotations


class HarmonyHubError(Exception):
    """Base class for all library errors."""


class HubUnavailableError(HarmonyHubError):
    """Network-level failure: hub unreachable, timeout, or connection closed."""


class ProvisioningError(HarmonyHubError):
    """HTTP provisioning POST returned malformed or error payload."""


class ProtocolError(HarmonyHubError):
    """WebSocket request timed out or returned an unexpected envelope."""


class CommandNotFoundError(HarmonyHubError):
    """Logical key or raw command does not exist on the target device."""

    def __init__(
        self, command: str, device: str, *, available: list[str] | None = None
    ) -> None:
        self.command = command
        self.device = device
        self.available = available or []
        msg = f"Command {command!r} not found on device {device!r}"
        if self.available:
            preview = ", ".join(self.available[:10])
            more = (
                ""
                if len(self.available) <= 10
                else f" (+{len(self.available) - 10} more)"
            )
            msg += f". Available: {preview}{more}"
        super().__init__(msg)


class AmbiguousRoutingError(HarmonyHubError):
    """Multiple devices could service the same logical key. Caller must disambiguate."""

    def __init__(self, *, key: str, candidates: list[str]) -> None:
        self.key = key
        self.candidates = candidates
        super().__init__(
            f"Routing for key {key!r} is ambiguous. Candidates: {candidates}. "
            "Pass an explicit --device."
        )
