# Troubleshooting

## `WebSocket connect failed: server rejected WebSocket connection: HTTP 401`

The hub rejected the handshake. Two causes:

- **Missing `Origin` header.** The lib passes `origin=HUB_ORIGIN` to
  `websockets.connect`. Check that nothing downstream strips it.
- **`domain=` parameter is a full URL.** The hub returns `discoveryServer`
  as e.g. `https://svcs.myharmony.com/Discovery/Discovery.svc`. The library
  extracts the bare host before opening the WebSocket
  (`harmonyhub/protocol/websocket.py:_domain_host`).

## `Request 'vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction' timed out`

`holdAction` is fire-and-forget — the hub does not return a correlated reply.
Use `WebSocketTransport.notify` instead of `request`. The library does this
already; if you see this error, you're either calling `request()` directly
or a code path was missed during the lookup.

## CLI reports success but nothing happens on the device

Several causes:

- **Wrong IR command name.** The hub's `function.name` (e.g. `Number1`)
  often differs from the IR command in `function.action.command` (e.g.
  `"1"`). The library handles this via `Device.command_actions`; if you're
  sending raw via `harmony send --command Number1`, the hub may reply with
  `code: 566 "Command not found for device id:<id>"` — switch to the inner
  command name (`harmony send --command 1`).
- **Wrong device.** Without `--device`, the lib routes via
  `[activity_routes]` for the current activity, then falls back to a single
  candidate. If two devices expose the same command, pass `--device`.
- **Hub IR database is wrong.** If `Mute` works but `VolumeUp` does the
  opposite, the IR pattern stored on the hub for `VolumeUp` is wrong.
  Re-learn the command in the Harmony app — the library only forwards what
  the hub fires.

## `Hub returned application code '404'`

The provisioning POST hit the hub but the hub didn't recognise the command.
You're likely on the wrong port (8088 is required) or the hub is in setup
mode and not yet provisioned.

## `Channel set` runs but TV doesn't switch

Default channel mode is `digits_then_enter`. The lib sends each digit, then
`Enter` (or `OK` / `Select`, whichever the device exposes via the alias
chain). If your channel device has no `Enter`-family command, the channel
will not commit on its own — disable `send_enter` and confirm manually, or
re-learn the OK button on the Harmony app.

## `harmony` command not found

The script is installed inside the project's venv (`.venv.mac/bin/harmony`).
Either:

- `source .venv.mac/bin/activate` and call `harmony` directly
- Call `.venv.mac/bin/harmony …` with the absolute path
- `uv run harmony …` — uv resolves the script from the project venv

## Yamaha AVR volume moves only 0.5 dB per press

That's the AVR's native IR step. Configure `[volume]` to multi-press:

```toml
[volume]
repeat = 4
inter_press_delay_ms = 80
```

Now `harmony key volume-up` fires `VolumeUp` four times → 2 dB per logical
press. `mute` is unaffected (always single-shot).
