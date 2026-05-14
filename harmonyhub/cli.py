import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from harmonyhub.exceptions import (
    AmbiguousRoutingError,
    CommandNotFoundError,
    HarmonyHubError,
    HubUnavailableError,
    ProtocolError,
    ProvisioningError,
)
from harmonyhub.service import HarmonyService, to_jsonable

_EXIT_USAGE = 2
_EXIT_UNAVAILABLE = 10
_EXIT_PROTOCOL = 11
_EXIT_NOT_FOUND = 12
_EXIT_AMBIGUOUS = 13

app = typer.Typer(
    add_completion=True,
    help="Local control of the Logitech Harmony Hub.",
    no_args_is_help=True,
)
activities_app = typer.Typer(help="Activity operations", no_args_is_help=True)
devices_app = typer.Typer(help="Device operations", no_args_is_help=True)
device_app = typer.Typer(help="Single-device shortcuts", no_args_is_help=True)
key_app = typer.Typer(help="Logical key dispatch", no_args_is_help=True)
channel_app = typer.Typer(help="Channel control", no_args_is_help=True)
config_app = typer.Typer(help="Hub-configuration helpers", no_args_is_help=True)

app.add_typer(activities_app, name="activities")
app.add_typer(devices_app, name="devices")
app.add_typer(device_app, name="device")
app.add_typer(key_app, name="key")
app.add_typer(channel_app, name="channel")
app.add_typer(config_app, name="config")

_stderr = Console(stderr=True)
_stdout = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _emit_json(payload: Any) -> None:
    _stdout.print_json(json.dumps(to_jsonable(payload), default=str))


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except HubUnavailableError as exc:
        _stderr.print(f"[red]Hub unavailable:[/red] {exc}")
        raise typer.Exit(_EXIT_UNAVAILABLE) from exc
    except (ProtocolError, ProvisioningError) as exc:
        _stderr.print(f"[red]Protocol error:[/red] {exc}")
        raise typer.Exit(_EXIT_PROTOCOL) from exc
    except AmbiguousRoutingError as exc:
        _stderr.print(f"[yellow]Ambiguous routing:[/yellow] {exc}")
        raise typer.Exit(_EXIT_AMBIGUOUS) from exc
    except CommandNotFoundError as exc:
        _stderr.print(f"[yellow]Not found:[/yellow] {exc}")
        raise typer.Exit(_EXIT_NOT_FOUND) from exc
    except HarmonyHubError as exc:
        _stderr.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(_EXIT_USAGE) from exc


# --------------------------------------------------------------------- top level


@app.callback()
def _root(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Verbose logging on stderr."
    ),
) -> None:
    _setup_logging(verbose)


@app.command()
def discover(
    name: str | None = typer.Option(
        None,
        "--name",
        help="Filter by hub friendly name (substring, case-insensitive).",
    ),
    remote_id: str | None = typer.Option(
        None, "--id", help="Filter by hub remote ID (substring, case-insensitive)."
    ),
    timeout: float = typer.Option(
        30.0, "--timeout", help="Discovery timeout in seconds."
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Discover Harmony Hubs on the local network via mDNS."""

    async def _go() -> None:
        from harmonyhub.discovery import discover as discover_hubs

        hubs: list[dict[str, str | None]] = []
        async for hub in discover_hubs(timeout=timeout):
            # Apply filters
            if name and (
                hub.friendly_name is None
                or name.lower() not in hub.friendly_name.lower()
            ):
                continue
            if remote_id and remote_id.lower() not in hub.remote_id.lower():
                continue
            hubs.append(
                {
                    "host": hub.host,
                    "friendly_name": hub.friendly_name or "-",
                    "remote_id": hub.remote_id,
                }
            )

        if json_out:
            _emit_json(hubs)
        elif not hubs:
            _stderr.print("[yellow]No Harmony Hubs discovered.[/yellow]")
            raise typer.Exit(_EXIT_NOT_FOUND)
        else:
            table = Table(title="Discovered Harmony Hubs")
            table.add_column("Host")
            table.add_column("Friendly Name")
            table.add_column("Remote ID")
            for hub in hubs:
                table.add_row(hub["host"], hub["friendly_name"], hub["remote_id"])
            _stdout.print(table)

    _run(_go())


@app.command()
def info(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Print hub identity (remote-id, redacted email, firmware)."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            data = await service.client.get_info()
        if json_out:
            _emit_json(data)
        else:
            _stdout.print(f"[bold]Host:[/bold] {data.host}")
            _stdout.print(f"Remote ID: {data.remote_id}")
            _stdout.print(f"Friendly name: {data.friendly_name or '-'}")
            _stdout.print(f"Firmware: {data.firmware_version or '-'}")
            _stdout.print(f"Email: {data.email_redacted or '-'}")
            _stdout.print(f"Discovery server: {data.discovery_server or '-'}")

    _run(_go())


@app.command()
def status(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show current activity, last channel, and connection state."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            data = await service.client.get_status()
        if json_out:
            _emit_json(data)
        else:
            current = data.current_activity
            _stdout.print(f"Activity: {current.activity_label or current.activity_id}")
            _stdout.print(
                f"Last channel: {data.last_channel or '-'} (source: {data.last_channel_source})"
            )
            _stdout.print(f"Connected: {data.connected}")

    _run(_go())


@app.command(name="power-off")
def power_off(host: str | None = typer.Option(None, "--host")) -> None:
    """Run the PowerOff activity."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            await service.client.power_off()

    _run(_go())


@app.command()
def listen(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Stream spontaneous hub events to stdout until Ctrl+C."""

    async def _go() -> None:
        async with HarmonyService(host, connection_mode="persistent") as service:
            async for event in service.client.listen():
                if json_out:
                    _emit_json(event)
                else:
                    _stdout.print(f"[cyan]{event.type or '?'}[/cyan] {event.data!r}")

    try:
        _run(_go())
    except KeyboardInterrupt:
        raise typer.Exit(0) from None


@app.command()
def send(
    device: str = typer.Option(..., "--device"),
    command: str = typer.Option(..., "--command"),
    hold_ms: int = typer.Option(0, "--hold-ms"),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Send a raw Harmony IR command to a device (debugging)."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.send_command(device, command, hold_ms=hold_ms)
        if json_out:
            _emit_json(result)
        elif not result.success:
            _stderr.print(f"[red]Failed:[/red] {result.error}")
            raise typer.Exit(_EXIT_PROTOCOL)

    _run(_go())


@app.command()
def doctor(host: str | None = typer.Option(None, "--host")) -> None:
    """Run a diagnostic check (host → port 8088 → provisioning → WS → config)."""

    async def _go() -> None:
        ok = True

        async with HarmonyService(host) as service:
            _stdout.print("[green]✓[/green] WebSocket connected")
            info = await service.client.get_info()
            _stdout.print(
                f"[green]✓[/green] Provisioning OK (remote-id: {info.remote_id})"
            )
            config = await service.client.get_config()
            _stdout.print(
                f"[green]✓[/green] Config loaded ({len(config.activities)} activities, "
                f"{len(config.devices)} devices)"
            )
            current = await service.client.get_current_activity()
            _stdout.print(
                f"[green]✓[/green] Current activity: {current.activity_label or current.activity_id}"
            )

        if not ok:
            raise typer.Exit(_EXIT_PROTOCOL)

    _run(_go())


# --------------------------------------------------------------------- activities


@activities_app.command("list")
def activities_list(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            items = await service.client.list_activities()
        if json_out:
            _emit_json(items)
            return
        table = Table(title="Activities")
        table.add_column("ID")
        table.add_column("Label")
        table.add_column("Power-off")
        for activity in items:
            table.add_row(
                activity.id, activity.label, "yes" if activity.is_power_off else ""
            )
        _stdout.print(table)

    _run(_go())


@activities_app.command("current")
def activities_current(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            current = await service.client.get_current_activity()
        if json_out:
            _emit_json(current)
        else:
            _stdout.print(current.activity_label or current.activity_id)

    _run(_go())


@activities_app.command("start")
def activities_start(
    name: str = typer.Argument(..., help="Activity name or id."),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.start_activity(name)
        if json_out:
            _emit_json(result)
        else:
            _stdout.print(
                f"Started {result.activity_label or result.activity_id} "
                f"({result.transition_state})"
            )

    _run(_go())


# --------------------------------------------------------------------- devices


@devices_app.command("list")
def devices_list(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            items = await service.client.list_devices()
        if json_out:
            _emit_json(items)
            return
        table = Table(title="Devices")
        table.add_column("ID")
        table.add_column("Label")
        table.add_column("Manufacturer")
        table.add_column("Commands")
        for dev in items:
            table.add_row(
                dev.id, dev.label, dev.manufacturer or "-", str(len(dev.commands))
            )
        _stdout.print(table)

    _run(_go())


@devices_app.command("commands")
def devices_commands(
    device: str = typer.Argument(...),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            commands = await service.client.list_device_commands(device)
        if json_out:
            _emit_json(commands)
        else:
            for command in commands:
                _stdout.print(command)

    _run(_go())


@device_app.command("power-on")
def device_power_on(
    device: str = typer.Argument(...),
    host: str | None = typer.Option(None, "--host"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.device_power_on(device)
        if not result.success:
            _stderr.print(f"[red]Failed:[/red] {result.error}")
            raise typer.Exit(_EXIT_NOT_FOUND)

    _run(_go())


@device_app.command("power-off")
def device_power_off(
    device: str = typer.Argument(...),
    host: str | None = typer.Option(None, "--host"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.device_power_off(device)
        if not result.success:
            _stderr.print(f"[red]Failed:[/red] {result.error}")
            raise typer.Exit(_EXIT_NOT_FOUND)

    _run(_go())


# --------------------------------------------------------------------- keys


def _key_command(key: str) -> Any:
    def _impl(
        device: str | None = typer.Option(None, "--device"),
        host: str | None = typer.Option(None, "--host"),
    ) -> None:
        async def _go() -> None:
            async with HarmonyService(host) as service:
                result = await service.client.send_key(key, device=device)
            if not result.success:
                _stderr.print(f"[red]Failed:[/red] {result.error}")
                raise typer.Exit(_EXIT_NOT_FOUND)

        _run(_go())

    _impl.__name__ = key.replace("-", "_")
    return _impl


for _logical in (
    "volume-up",
    "volume-down",
    "mute",
    "channel-up",
    "channel-down",
    "ok",
    "back",
):
    key_app.command(_logical)(_key_command(_logical.replace("-", "_")))


@key_app.command("digit")
def key_digit(
    digit: int = typer.Argument(..., min=0, max=9),
    device: str | None = typer.Option(None, "--device"),
    host: str | None = typer.Option(None, "--host"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.send_key(f"digit_{digit}", device=device)
        if not result.success:
            _stderr.print(f"[red]Failed:[/red] {result.error}")
            raise typer.Exit(_EXIT_NOT_FOUND)

    _run(_go())


# --------------------------------------------------------------------- channel


@channel_app.command("set")
def channel_set(
    channel: str = typer.Argument(...),
    device: str | None = typer.Option(None, "--device"),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.set_channel(channel, device=device)
        if json_out:
            _emit_json(result)
        elif not result.success:
            _stderr.print(f"[red]Failed:[/red] {result.error}")
            raise typer.Exit(_EXIT_NOT_FOUND)

    _run(_go())


# --------------------------------------------------------------------- config


@config_app.command("pull")
def config_pull(
    host: str | None = typer.Option(None, "--host"),
    out: Path | None = typer.Option(
        None, "--out", help="Output file (default: stdout)."
    ),
) -> None:
    """Fetch the raw hub config and write it as JSON (default: stdout)."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            config = await service.client.get_config(refresh=True)
        payload = json.dumps(config.raw, indent=2, sort_keys=True)
        if out is None:
            _stdout.print_json(payload)
        else:
            out.write_text(payload + "\n", encoding="utf-8")

    _run(_go())


def main() -> None:  # pragma: no cover - thin entrypoint
    app()
