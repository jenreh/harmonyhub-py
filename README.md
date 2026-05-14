# harmonyhub-py

Local control of the Logitech Harmony Hub from Python — usable as a library,
a CLI, and an MCP server.

The library talks to the hub on the local network only (port 8088 over
WebSocket). No Logitech cloud round-trip is required after the one-time
provisioning POST that the hub itself answers locally.

## Installation

```bash
uv sync                          # uv-managed checkout (recommended; uses .venv.mac)
pip install -e .                 # or plain pip from the repo root
pip install -e .[dev]            # plus ruff / mypy / pytest
```

Python ≥ 3.14 is required (declared in `pyproject.toml`; matches the pinned
interpreter in `uv.lock` and `.python-version`).

## Quick start (library)

```python
import asyncio
from harmonyhub import HarmonyHubClient


async def main() -> None:
    async with HarmonyHubClient("192.168.178.50") as hub:
        info = await hub.get_info()
        print(f"Hub: {info.friendly_name} (remote-id: {info.remote_id})")

        for activity in await hub.list_activities():
            print(f"  {activity.label} (id={activity.id})")

        await hub.start_activity("Watch TV")
        await hub.send_key("volume_up")
        result = await hub.set_channel("101")
        print(f"Channel via {result.method}")


asyncio.run(main())
```

## Quick start (CLI)

```bash
export HARMONY_HUB_HOST=192.168.178.50

harmony info
harmony activities list
harmony activities start "Watch TV"
harmony key volume-up
harmony key mute
harmony key digit 5
harmony channel 101
harmony status
harmony doctor                          # end-to-end diagnostic
harmony discover                        # find Harmony Hubs
```

All read commands accept `--json` for machine-readable output. All logs go to
stderr, so stdout stays scriptable.

### CLI command reference

Every command resolves the hub host from (in order) `--host`, the
`HARMONY_HUB_HOST` env var, or `[hub].host` in `config.toml`.

#### Top-level

| Command                                                          | Purpose                                                                                    |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `harmony info [--json]`                                          | Hub identity: remote ID, redacted email, firmware, friendly name, discovery server.        |
| `harmony status [--json]`                                        | Current activity, last channel (library-tracked), connection state.                        |
| `harmony power-off`                                              | Run the `PowerOff` activity.                                                               |
| `harmony listen [--json]`                                        | Stream spontaneous hub events to stdout until Ctrl+C.                                      |
| `harmony send --device DEV --command CMD [--hold-ms N] [--json]` | Send a raw IR command name to a specific device. Bypasses logical-key routing and aliases. |
| `harmony doctor`                                                 | End-to-end diagnostic: host reachability → port 8088 → provisioning → WebSocket → config.  |
| `harmony discover [--name N] [--id ID] [--timeout S] [--json]`   | Find hubs on the LAN via SSDP M-SEARCH and a parallel /24 port scan.                       |
| `harmony channel <n> [--device DEV] [--json]`                    | Switch channels. `digits_then_enter` (default) or native `change_channel` per config.      |
| `harmony activities list/current/start …`                        | List, query, or switch activities (list, current, start).                                  |
| `harmony devices list/commands …`                                | List all devices and their IR commands (list, commands).                                   |
| `harmony device power-on/off <device>`                           | Power a single device on or off (power-on, power-off).                                     |
| `harmony key volume-up/down/mute/ok/back/digit …`                | Send a logical key with automatic routing (volume, channel, ok, back, digit).              |
| `harmony config pull/show/diff …`                                | Fetch, display, or diff the hub config (pull, show, diff).                                 |
| `harmony sequence list/run …`                                    | List and fire hub-defined macro sequences (list, run).                                     |

#### Activities — `harmony activities ...`

| Subcommand            | Purpose                                                       |
| --------------------- | ------------------------------------------------------------- |
| `list [--json]`       | All activities defined on the hub.                            |
| `current [--json]`    | The active activity (or `PowerOff`).                          |
| `start <name-or-id>`  | Switch to an activity. Triggers device power-ons via the hub. |

#### Devices — `harmony devices ...`

| Subcommand                                           | Purpose                                                                                  |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `list [--type KIND] [--json]`                        | All devices: ID, label, kind, manufacturer, command count. `--type` filters by kind.     |
| `commands <device> [--group G] [--grouped] [--json]` | List commands; `--grouped` groups by control group, `--group <name>` restricts to one.   |

Recognised `--type` values: `television`, `avreceiver`, `speaker`, `stb`, `game`,
`appletv`, `other`.

#### Single-device shortcuts — `harmony device ...`

| Subcommand              | Purpose                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `power-on <device>`     | `PowerOn` (falls back to `PowerToggle` if configured).        |
| `power-off <device>`    | `PowerOff`.                                                   |

#### Logical keys — `harmony key ...`

Each subcommand accepts `--device` to override routing and `--host` for the
hub. Without `--device`, the key routes via `[activity_routes.<label>]` in
`config.toml`; if no route is configured the lib picks the single device
that owns the command, or fails with an ambiguity error.

| Subcommand       | Default route field                              | Notes                                                                       |
| ---------------- | ------------------------------------------------ | --------------------------------------------------------------------------- |
| `volume-up`      | `volume_device`                                  | Honours `[volume]` repeat / hold_ms.                                        |
| `volume-down`    | `volume_device`                                  | Honours `[volume]` repeat / hold_ms.                                        |
| `mute`           | `volume_device`                                  | Single press; toggles AVR/TV mute.                                          |
| `channel-up`     | `channel_device`                                 |                                                                             |
| `channel-down`   | `channel_device`                                 |                                                                             |
| `ok`             | `navigation_device`                              | Alias chain: `OK` → `Enter` → `Select` → `DirectionSelect`.                 |
| `back`           | `navigation_device`                              | Alias chain: `Back` → `Return` → `Exit` → `PreviousMenu` → `DirectionBack`. |
| `digit <0-9>`    | `number_device` (falls back to `channel_device`) | Sends `Number0`…`Number9` (or `0`…`9`, depending on hub config).            |

`harmony key digit 5` is the canonical form; `harmony key 5` is not exposed
— digits go through the `digit` subcommand.

#### Channel control — `harmony channel`

`harmony channel <number> [--device DEV] [--json]`

Switch channels. In `digits_then_enter` mode, presses each digit then `Enter`;
in `change_channel` mode, fires the hub's native `changeChannel` command. The
target device is taken from `[activity_routes].channel_device` for the active
activity, or auto-resolved. Pass `--device` to override.

#### Hub-config helpers — `harmony config ...`

- `pull [--out PATH]` — fetch the raw hub config and write it as JSON
  (stdout when `--out` omitted).
- `show [--json]` — parsed summary: version, locale, devices (kind,
  capabilities, control groups), activities (roles), sequences.
- `diff [--json]` — compare the on-disk cached config to a fresh pull;
  surfaces added/removed devices, activities, commands, and `configVersion`
  bumps.

#### Sequences — `harmony sequence ...`

Hub-defined macros (multi-step IR runs configured in the Harmony app):

| Subcommand          | Purpose                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `list [--json]`     | List sequences with ID, label, and step count.                     |
| `run <sequence-id>` | Fire every step in order. Reports per-step success / failure rows. |

### Shell completions (zsh)

Auto-install (modifies `~/.zshrc`):

```bash
harmony --install-completion zsh
exec zsh    # or open a new shell
```

Manual install (no edits to `~/.zshrc`; uses `$fpath`):

```bash
mkdir -p ~/.zfunc
harmony --show-completion zsh > ~/.zfunc/_harmony
# add to ~/.zshrc once:
#   fpath=(~/.zfunc $fpath)
#   autoload -U compinit && compinit
```

Completion drives off the live binary, so it stays in sync as new subcommands
are added.

### Exit codes

| Code  | Meaning                                          |
| ----- | ------------------------------------------------ |
| `0`   | success                                          |
| `2`   | usage / validation error                         |
| `10`  | hub unavailable on the network                   |
| `11`  | protocol error (timeout, malformed payload)      |
| `12`  | command or alias not found                       |
| `13`  | routing ambiguous — pass an explicit `--device`  |

## Configuration

The library reads `~/.config/harmony-local/config.toml` (or `%APPDATA%` on
Windows). Every value can be overridden by an environment variable or a CLI
argument (precedence: CLI > env > file > default).

```toml
[hub]
host = "192.168.178.50"

[connection]
mode = "persistent"            # persistent | ondemand
protocol = "websocket"         # websocket | xmpp
keepalive_interval_s = 50
request_timeout_s = 10

[channel]
mode = "digits_then_enter"     # digits_then_enter | change_channel
inter_digit_delay_ms = 150
send_enter = true

[volume]
# Fired per `harmony key volume-up` / `volume-down` (mute is always single).
repeat = 1                     # IR presses per logical key (raise for AVRs with fine steps, e.g. 4 → 2 dB on Yamaha)
hold_ms = 0                    # extra IR hold per press (some AVRs need ≥100 ms to register repeat-frames)
inter_press_delay_ms = 80      # gap between repeats when repeat > 1

[activity_routes."Watch TV"]
volume_device = "Denon AVR"
channel_device = "Vodafone Receiver"
navigation_device = "Vodafone Receiver"
number_device = "Vodafone Receiver"
```

Recognised environment variables: `HARMONY_HUB_HOST`, `HARMONY_PROTOCOL`,
`HARMONY_CONNECTION_MODE`.

## MCP server

`harmony-mcp` runs the FastMCP server over stdio. Wire it into Claude Desktop:

```json
{
  "mcpServers": {
    "harmony": {
      "command": "harmony-mcp",
      "args": [],
      "env": { "HARMONY_HUB_HOST": "192.168.178.50" }
    }
  }
}
```

Tools exposed:

- `harmony_get_status` — current activity, last channel, connection state.
- `harmony_list_activities`, `harmony_start_activity`, `harmony_power_off`.
- `harmony_list_devices`, `harmony_list_device_commands`.
- `harmony_device_power_on`, `harmony_device_power_off`.
- `harmony_send_key` — typed `LogicalKey` (volume/channel up-down, digits,
  ok, enter, back, off). Routing falls back to TOML `activity_routes`, then
  auto-resolution.
- `harmony_send_command` — raw IR command on a device (for vendor-specific
  buttons not covered by `send_key`).
- `harmony_set_channel` — `digits_then_enter` or native `change_channel`.
- `harmony_refresh_config` — re-fetch and replace the cached config.

Resources exposed: `harmony://config`, `harmony://activities`,
`harmony://devices`, `harmony://status`.

The server never logs to stdout (that would corrupt the MCP framing) and does
not return raw account IDs or unredacted email addresses.

## Natural-language skill

A drop-in skill for Claude Code / Claude Desktop lives at
[`skill/harmonyhub/SKILL.md`](skill/harmonyhub/SKILL.md). It teaches the
model to translate voice-style requests (*"schalte Pro7 ein"*, *"lauter"*,
*"alles aus"*) into the matching MCP tool calls or CLI invocations.

Highlights:

- Hard rule: channel requests are only valid when the active activity is
  `Fernsehen`. The skill checks `harmony_get_status` first and starts the
  activity if needed before calling `harmony_set_channel`.
- Channel-name → number map (ARD=1, ZDF=2, RTL=3, Sat1=4, Pro7=5, …).
- Activity aliases for this hub: `Fernsehen`, `Apple TV sehen`,
  `Musik hören`, `TV`, `PowerOff`.
- Volume / mute / OK / Back / channel ±/digit routing tables.
- Replies in the user's language in one short sentence — no tool names, no
  JSON.

See [`docs/skill.md`](docs/skill.md) for installation notes.

## What the library will *not* tell you

The hub is a one-way IR transmitter for most operations, so the library is
honest about what it cannot know:

| Question                                              | Verdict                                                                                              |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Which activity is active?                             | Reliable — read directly from the hub.                                                               |
| What is the current channel?                          | Unknown to the hub. Tracked only when set via this library, with `last_channel_source` flagged.      |
| Is a specific device powered on?                      | Inferred from the active activity; unverified.                                                       |
| Was the user pressing buttons on the original remote? | Invisible to the hub.                                                                                |

If anything outside Harmony changed a device's state, the library will not
pretend otherwise. Run `harmony status` to inspect what is actually known.

## Documentation

| File                                               | Summary                                                                             |
| -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| [docs/protocol.md](https://github.com/jenreh/harmonyhub-py/blob/main/docs/protocol.md)               | Raw WebSocket/HTTP payloads the library uses; reverse-engineered hub wire format.   |
| [docs/routing.md](https://github.com/jenreh/harmonyhub-py/blob/main/docs/routing.md)                 | How logical keys resolve to a target device — precedence rules and config examples. |
| [docs/skill.md](https://github.com/jenreh/harmonyhub-py/blob/main/docs/skill.md)                     | Installation guide for the Claude Code natural-language agent skill.                |
| [docs/troubleshooting.md](https://github.com/jenreh/harmonyhub-py/blob/main/docs/troubleshooting.md) | Common errors (HTTP 401, timeout, provisioning failures) and fixes.                 |

## Tests

```bash
pytest                                       # unit + simulator tests, no real hub needed
HARMONY_HUB_HOST=... pytest -m integration   # opt-in real-hub smoke test
```

## Repository layout

See `spec/harmony_hub_implementierungsplan(1).md` for the full design plan.
Runtime code lives in `harmonyhub/`:

```bash
harmonyhub/
├── client.py          # HarmonyHubClient — public API
├── models.py          # Frozen dataclasses (Device.command_actions maps function.name → IR command)
├── exceptions.py      # Error hierarchy
├── aliases.py         # Logical-key → IR-command fallbacks
├── status.py          # last_channel persistence
├── cache.py           # XDG paths, JSON cache helpers
├── config.py          # TOML loader + env overlay (Connection / Channel / Volume / ActivityRoute)
├── discovery.py       # mDNS stub (post-MVP)
├── cli.py             # Typer CLI (zsh completion via `--install-completion zsh`)
├── mcp_server.py      # FastMCP server
├── simulator.py       # Fake hub (WebSocket only — HTTP mocked in tests)
└── protocol/
    ├── http.py        # Provisioning POST (exports HUB_ORIGIN constant)
    ├── websocket.py   # WebSocket transport — request/response + fire-and-forget notify()
    └── xmpp.py        # Stub (post-MVP)
```
