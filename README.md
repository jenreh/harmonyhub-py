# harmonyhub-py

![Version](https://img.shields.io/badge/version-0.2.6-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)
[![Python](https://img.shields.io/badge/python-3.14%2B-orange)](https://www.python.org)

**harmonyhub-py** talks directly to your hub over WebSocket on the local network — no Logitech cloud, no account, no internet required after the initial one-time provisioning.

---

## Features

- **Pure local control** — WebSocket on port 8088; provisioning POST is answered by the hub itself
- **Async Python library** — `async with HarmonyHubClient("192.168.1.x") as hub: ...`
- **Rich CLI** — human-readable tables or `--json` for scripts and pipes
- **MCP server** — expose your hub as tools to Claude or any MCP client
- **Logical-key routing** — maps `volume_up`, `channel_down`, `ok`, etc. to the right device automatically
- **Hub discovery** — SSDP M-SEARCH + parallel `/24` port scan
- **Simulator** — fake hub for tests; no real hardware needed

---

## Installation

```bash
pip install harmonyhub-py
```

Requires Python 3.14+.

---

## Quick start

### 1. Discover your hub

```bash
harmony discover
```

```text
           Discovered Harmony Hubs
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Host           ┃ Friendly Name ┃ Remote ID ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 192.168.178.50 │ Harmony Hub   │ 12345678  │
└────────────────┴───────────────┴───────────┘
```

### 2. Point the CLI at the hub

```bash
export HARMONY_HUB_HOST=192.168.178.50
harmony status
```

```text
Activity: PowerOff
Last channel: 5 (source: library)
Connected: True
```

### 3. Use it

```bash
harmony activities list
harmony activities start "Watch TV"
harmony key volume-up
harmony channel 101
```

---

## CLI reference

```text
harmony [--host IP] [--json]
```

| Command | Description |
| --- | --- |
| `harmony discover` | Find hubs on the LAN via SSDP + `/24` port scan |
| `harmony info` | Hub identity: remote ID, firmware, friendly name |
| `harmony status` | Current activity, last channel, connection state |
| `harmony power-off` | Run the `PowerOff` activity |
| `harmony listen` | Stream real-time hub events to stdout |
| `harmony activities list/current/start` | List, query, or switch activities |
| `harmony devices list/commands` | List devices and their IR commands |
| `harmony device power-on/off <device>` | Power a single device on or off |
| `harmony key volume-up/down/mute/ok/back/digit` | Send a logical key with automatic routing |
| `harmony channel <n>` | Switch channel (`digits_then_enter` or `change_channel`) |
| `harmony send --device DEV --command CMD` | Send a raw IR command to a specific device |
| `harmony config pull/show/diff` | Fetch, display, or diff the hub config |
| `harmony sequence list/run` | List and fire hub-defined macro sequences |
| `harmony doctor` | End-to-end diagnostic: network → provisioning → WebSocket → config |

Use `--json` for machine-readable output on any read command. All log output goes to stderr; stdout stays scriptable.

For the full subcommand reference see [docs/routing.md](docs/routing.md).

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `2` | usage / validation error |
| `10` | hub unavailable on the network |
| `11` | protocol error (timeout, malformed payload) |
| `12` | command or alias not found |
| `13` | routing ambiguous — pass an explicit `--device` |

### Shell completions (zsh)

```bash
harmony --install-completion zsh
exec zsh
```

---

## Python library

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

---

## MCP server

**harmonyhub-py** ships with an MCP server that exposes the hub as tools for Claude or any MCP-compatible client.

### Claude Desktop

Add to `claude_desktop_config.json`:

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

### VS Code (agent mode)

```json
{
  "mcp": {
    "servers": {
      "harmony": {
        "command": "harmony-mcp",
        "type": "stdio",
        "env": { "HARMONY_HUB_HOST": "192.168.178.50" }
      }
    }
  }
}
```

### Available MCP tools

`harmony_get_status` · `harmony_list_activities` · `harmony_start_activity` · `harmony_power_off` · `harmony_list_devices` · `harmony_list_device_commands` · `harmony_device_power_on` · `harmony_device_power_off` · `harmony_send_key` · `harmony_send_command` · `harmony_set_channel` · `harmony_refresh_config`

Resources: `harmony://config` · `harmony://activities` · `harmony://devices` · `harmony://status`

---

## Agent skill

`skill/harmonyhub/SKILL.md` follows the [Agent Skills open standard](https://agentskills.io) and works across GitHub Copilot (VS Code, CLI, cloud agent), Claude Code, and Cursor — write once, use everywhere.

It teaches the model to translate voice-style requests (*"schalte Pro7 ein"*, *"lauter"*, *"alles aus"*) into the matching MCP tool calls or `harmony` CLI invocations. Replies stay in the user's language — no tool names, no JSON.

### Skill installation

**Project skill** (one repository):

```bash
cp -r skill/harmonyhub /your-project/.agents/skills/harmonyhub
# or keep in sync via symlink:
ln -s "$(pwd)/skill/harmonyhub" /your-project/.agents/skills/harmonyhub
```

**Personal skill** (every project on your machine):

```bash
cp -r skill/harmonyhub ~/.agents/skills/harmonyhub      # generic / Copilot
cp -r skill/harmonyhub ~/.claude/skills/harmonyhub       # Claude Code
```

> [!TIP]
> If you cloned harmonyhub-py, the skill is already installed as `.agents/skills/harmonyhub` — no extra step needed.

See [docs/skill.md](docs/skill.md) for full installation notes.

---

## Configuration

Config file: `~/.config/harmony-local/config.toml`

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
repeat = 1                     # IR presses per logical key (e.g. 4 → 2 dB steps on a Yamaha AVR)
hold_ms = 0                    # extra hold per press in ms
inter_press_delay_ms = 80      # gap between repeats when repeat > 1

[activity_routes."Watch TV"]
volume_device = "Denon AVR"
channel_device = "Vodafone Receiver"
navigation_device = "Vodafone Receiver"
number_device = "Vodafone Receiver"
```

Environment variable overrides:

| Variable | Overrides |
| --- | --- |
| `HARMONY_HUB_HOST` | `hub.host` |
| `HARMONY_PROTOCOL` | `connection.protocol` |
| `HARMONY_CONNECTION_MODE` | `connection.mode` |

Precedence: CLI flag > env var > config file > default.

---

## Limitations

The hub is a one-way IR transmitter for most operations, so the library is honest about what it cannot know:

| Question | Verdict |
| --- | --- |
| Which activity is active? | Reliable — read directly from the hub |
| What is the current channel? | Unknown to the hub; tracked only when set via this library (`last_channel_source` flagged) |
| Is a specific device powered on? | Inferred from the active activity; unverified |
| Did the user press the original remote? | Invisible to the hub |

Run `harmony status` to inspect what is actually known.

---

## Development

```bash
git clone https://github.com/jenreh/harmonyhub-py
cd harmonyhub-py
uv sync --extra dev
task test     # pytest with coverage
task lint     # ruff + mypy
task format   # ruff format
```

> [!NOTE]
> A `FakeHub` simulator (`harmonyhub.simulator`) is included for use in tests — no real Harmony Hub required.

---

## Documentation

| File | Summary |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | Raw WebSocket/HTTP payloads; reverse-engineered hub wire format |
| [docs/routing.md](docs/routing.md) | How logical keys resolve to a device — precedence rules and config examples |
| [docs/skill.md](docs/skill.md) | Installation guide for the natural-language agent skill |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors (HTTP 401, timeout, provisioning failures) and fixes |
