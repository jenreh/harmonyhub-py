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
config_app = typer.Typer(help="Hub-configuration helpers", no_args_is_help=True)
sequence_app = typer.Typer(help="Hub macro sequences", no_args_is_help=True)

app.add_typer(activities_app, name="activities")
app.add_typer(devices_app, name="devices")
app.add_typer(device_app, name="device")
app.add_typer(key_app, name="key")
app.add_typer(config_app, name="config")
app.add_typer(sequence_app, name="sequence")

_stderr = Console(stderr=True)
_stdout = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.ERROR,
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
    """Discover Harmony Hubs on the local network via SSDP and subnet scan."""

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
        table.add_column("Type")
        table.add_column("Volume")
        table.add_column("Channel")
        table.add_column("Display")
        table.add_column("Power-off")
        for activity in items:
            roles = activity.roles
            table.add_row(
                activity.id,
                activity.label,
                activity.type or "-",
                roles.volume_device_id or "-",
                roles.channel_device_id or "-",
                roles.display_device_id or "-",
                "yes" if activity.is_power_off else "",
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
    kind: str | None = typer.Option(
        None,
        "--type",
        "--kind",
        help="Filter by normalised kind: television, avreceiver, speaker, stb, game, appletv, other.",
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            items = await service.client.list_devices(kind=kind)
        if json_out:
            _emit_json(items)
            return
        table = Table(title="Devices")
        table.add_column("ID")
        table.add_column("Label")
        table.add_column("Kind")
        table.add_column("Manufacturer")
        table.add_column("Commands")
        for dev in items:
            table.add_row(
                dev.id,
                dev.label,
                dev.kind or "-",
                dev.manufacturer or "-",
                str(len(dev.commands)),
            )
        _stdout.print(table)

    _run(_go())


@devices_app.command("commands")
def devices_commands(
    device: str = typer.Argument(...),
    host: str | None = typer.Option(None, "--host"),
    group: str | None = typer.Option(
        None, "--group", help="Restrict output to a single control group (e.g. Volume)."
    ),
    grouped: bool = typer.Option(
        False, "--grouped", help="Print commands grouped by control group."
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            groups = await service.client.list_device_command_groups(device)
            commands = await service.client.list_device_commands(device)
        if json_out:
            if grouped or group is not None:
                payload = {
                    k: list(v)
                    for k, v in groups.items()
                    if group is None or k.casefold() == group.casefold()
                }
                _emit_json(payload)
            else:
                _emit_json(commands)
            return
        if group is not None:
            wanted = group.casefold()
            for name, cmds in groups.items():
                if name.casefold() == wanted:
                    for command in cmds:
                        _stdout.print(command)
                    return
            _stderr.print(f"[yellow]No group {group!r} on device.[/yellow]")
            return
        if grouped:
            for name, cmds in groups.items():
                _stdout.print(f"[bold]{name}[/bold]")
                for command in cmds:
                    _stdout.print(f"  {command}")
            return
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


@app.command()
def channel(
    number: str = typer.Argument(..., help="Channel number to switch to."),
    device: str | None = typer.Option(None, "--device"),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Switch to a channel number."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            result = await service.client.set_channel(number, device=device)
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


@config_app.command("show")
def config_show(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show a parsed summary of the hub configuration."""

    async def _go() -> None:
        async with HarmonyService(host) as service:
            config = await service.client.get_config()
        if json_out:
            _emit_json(
                {
                    "config_version": config.config_version,
                    "locale": config.locale,
                    "activities": list(config.activities),
                    "devices": list(config.devices),
                    "sequences": list(config.sequences),
                    "content": config.content,
                }
            )
            return
        _stdout.print(
            f"[bold]Config version:[/bold] {config.config_version or '-'}  "
            f"[bold]Locale:[/bold] {config.locale or '-'}"
        )
        dev_table = Table(title="Devices")
        for col in ("ID", "Label", "Kind", "Manufacturer", "Capabilities", "Groups"):
            dev_table.add_column(col)
        for dev in config.devices:
            dev_table.add_row(
                dev.id,
                dev.label,
                dev.kind or "-",
                dev.manufacturer or "-",
                ", ".join(dev.capability_labels) or "-",
                ", ".join(dev.command_groups) or "-",
            )
        _stdout.print(dev_table)
        act_table = Table(title="Activities")
        for col in ("ID", "Label", "Type", "Volume", "Channel", "Display"):
            act_table.add_column(col)
        for activity in config.activities:
            roles = activity.roles
            act_table.add_row(
                activity.id,
                activity.label,
                activity.type or "-",
                roles.volume_device_id or "-",
                roles.channel_device_id or "-",
                roles.display_device_id or "-",
            )
        _stdout.print(act_table)
        if config.sequences:
            _stdout.print(
                f"[bold]Sequences:[/bold] {len(config.sequences)} "
                f"({', '.join(s.label for s in config.sequences)})"
            )

    _run(_go())


@config_app.command("diff")
def config_diff(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compare on-disk cached config to a freshly pulled one."""
    from harmonyhub.cache import hub_cache_dir, read_json
    from harmonyhub.parser import parse_config

    async def _go() -> None:
        async with HarmonyService(host) as service:
            await service.client.connect()
            provision = service.client._provision  # noqa: SLF001
            cached_raw = None
            if provision is not None:
                cached_entry = read_json(
                    hub_cache_dir(provision.remote_id) / "config.json"
                )
                if isinstance(cached_entry, dict):
                    cached_raw = cached_entry.get("data")
            fresh = await service.client.get_config(refresh=True)
        cached = parse_config(cached_raw) if isinstance(cached_raw, dict) else None
        diff = _config_diff(cached, fresh)
        if json_out:
            _emit_json(diff)
            return
        if not any(diff.values()):
            _stdout.print("[green]No differences.[/green]")
            return
        for section, entries in diff.items():
            if not entries:
                continue
            _stdout.print(f"[bold]{section}[/bold]")
            for entry in entries:
                _stdout.print(f"  {entry}")

    _run(_go())


def _config_diff(cached: Any, fresh: Any) -> dict[str, list[str]]:
    cached_devices = {d.id: d for d in cached.devices} if cached else {}
    fresh_devices = {d.id: d for d in fresh.devices}
    cached_activities = {a.id: a for a in cached.activities} if cached else {}
    fresh_activities = {a.id: a for a in fresh.activities}

    added_devices = [
        f"+ {d.label} ({d.id})"
        for did, d in fresh_devices.items()
        if did not in cached_devices
    ]
    removed_devices = [
        f"- {d.label} ({d.id})"
        for did, d in cached_devices.items()
        if did not in fresh_devices
    ]
    added_activities = [
        f"+ {a.label} ({a.id})"
        for aid, a in fresh_activities.items()
        if aid not in cached_activities
    ]
    removed_activities = [
        f"- {a.label} ({a.id})"
        for aid, a in cached_activities.items()
        if aid not in fresh_activities
    ]
    command_changes: list[str] = []
    for did, dev in fresh_devices.items():
        if did not in cached_devices:
            continue
        cached_dev = cached_devices[did]
        added = set(dev.commands) - set(cached_dev.commands)
        removed = set(cached_dev.commands) - set(dev.commands)
        command_changes.extend(f"+ {dev.label}: {cmd}" for cmd in sorted(added))
        command_changes.extend(f"- {dev.label}: {cmd}" for cmd in sorted(removed))
    version_changes: list[str] = []
    if cached is not None and cached.config_version != fresh.config_version:
        version_changes.append(
            f"configVersion: {cached.config_version} → {fresh.config_version}"
        )
    return {
        "configVersion": version_changes,
        "devices": added_devices + removed_devices,
        "activities": added_activities + removed_activities,
        "commands": command_changes,
    }


# --------------------------------------------------------------------- sequences


@sequence_app.command("list")
def sequence_list(
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            items = await service.client.list_sequences()
        if json_out:
            _emit_json(items)
            return
        if not items:
            _stdout.print("[yellow]No sequences configured on this hub.[/yellow]")
            return
        table = Table(title="Sequences")
        table.add_column("ID")
        table.add_column("Label")
        table.add_column("Actions")
        for seq in items:
            table.add_row(seq.id, seq.label, str(len(seq.actions)))
        _stdout.print(table)

    _run(_go())


@sequence_app.command("run")
def sequence_run(
    sequence_id: str = typer.Argument(...),
    host: str | None = typer.Option(None, "--host"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    async def _go() -> None:
        async with HarmonyService(host) as service:
            results = await service.client.run_sequence(sequence_id)
        if json_out:
            _emit_json(results)
            return
        for result in results:
            status = "[green]ok[/green]" if result.success else "[red]fail[/red]"
            _stdout.print(f"{status} {result.device_id} {result.command}")

    _run(_go())


def main() -> None:  # pragma: no cover - thin entrypoint
    app()
