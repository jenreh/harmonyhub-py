# Local Harmony Hub protocol — payloads the library uses

This document captures the exact payloads sent and expected by `harmonyhub`.
The hub is not formally documented by Logitech; firmware updates may change
behaviour. Treat this as a working reference, not a contract.

## 1. Provisioning (HTTP POST, port 8088)

The library opens its WebSocket against
`ws://<HUB>:8088/?domain=<discoveryServer-host>&hubId=<activeRemoteId>`, and
both values come from a one-time HTTP POST.

```http
POST http://<HUB>:8088/
Origin: http://sl.dhg.myharmony.com
Content-Type: application/json
Accept: application/json
Accept-Charset: utf-8

{"id": 1, "cmd": "setup.account?getProvisionInfo", "params": {}}
```

Response (relevant fields only):

```json
{
  "data": {
    "activeRemoteId": "12345678",
    "accountId": "...",
    "email": "user@example.com",
    "discoveryServer": "https://svcs.myharmony.com/Discovery/Discovery.svc",
    "friendlyName": "Wohnzimmer",
    "currentFwVersion": "4.15.250"
  },
  "code": "200"
}
```

`accountId` and the raw `email` are **not** persisted by the library; only a
redacted form of the email appears in `HubInfo.email_redacted`.

The hub returns `discoveryServer` as a **full URL**, but the WebSocket
handshake's `domain=` parameter must be the **bare hostname** only. Passing
the URL verbatim makes the hub reject the upgrade with `HTTP 401`. The lib
strips the host via `urllib.parse.urlparse(...).hostname`
(`harmonyhub/protocol/websocket.py:_domain_host`). Falls back to
`svcs.myharmony.com` if the field is missing.

## 2. WebSocket envelope

The handshake **requires** the same `Origin: http://sl.dhg.myharmony.com`
header used on the HTTP POST. Without it the hub returns `HTTP 401`. The lib
passes it via `websockets.connect(..., origin=HUB_ORIGIN)` and reuses the
constant exported from `harmonyhub.protocol.http`.

Every request shares this envelope:

```json
{
  "hubId": "<activeRemoteId>",
  "timeout": 30,
  "hbus": {
    "cmd": "<command>",
    "id": "<uuid-hex>",
    "params": { }
  }
}
```

Most responses carry the same `id` at the **top level** (not inside `hbus`)
so they can be correlated. Spontaneous events have no `id` — they are
emitted by the hub when an activity is started, finished, or a state digest
changes — and are routed to the events queue.

**Not every command replies.** `holdAction` is fire-and-forget: the hub
never returns a correlated frame for press/release. The transport exposes
a `notify(cmd, params)` method that sends the envelope without registering
a pending future, used by `_press_release` to avoid a 10 s timeout on every
button.

The hub closes idle sockets after ~60 seconds, so the library pings every
50 s and reconnects with exponential backoff (1 → 2 → 4 … capped at 30 s).

## 3. Commands used by the library

| Purpose                          | `cmd`                                                                 | Reply? | Notes                                                                                      |
| -------------------------------- | --------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------ |
| Hub config (activities, devices) | `vnd.logitech.harmony/vnd.logitech.harmony.engine?config`             | yes    | Cached on disk after first fetch.                                                          |
| Current activity                 | `vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity` | yes    | Response: `data.result` (preferred) or `data.activityId`.                                  |
| State digest                     | `vnd.logitech.connect/vnd.logitech.statedigest?get`                   | yes    | Optional; supplies `configVersion` if present.                                             |
| Start activity                   | `vnd.logitech.harmony/vnd.logitech.harmony.engine?startactivity`      | yes    | `params={"activityId": "<id>", "timestamp": "<ms>"}`. Progress frames reuse the same `id`. |
| Start activity (fallback)        | `harmony.activityengine?runactivity`                                  | yes    | Used only when the primary command fails.                                                  |
| Press / release button           | `vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction`         | **no** | Fire-and-forget. Sent via `transport.notify(...)`. Hub never returns a correlated frame.   |
| Change channel (native)          | `harmony.engine?changeChannel`                                        | yes    | Only used when `[channel].mode = "change_channel"`.                                        |
| Sync hub config                  | `setup.sync` (HTTP POST)                                              | yes    | Triggered manually after editing the hub config.                                           |

### holdAction payload

```json
{
  "status": "press",
  "timestamp": "0",
  "verb": "render",
  "action": "{\"command\":\"1\",\"type\":\"IRCommand\",\"deviceId\":\"78652298\"}"
}
```

The library sends `press`, sleeps for `max(hold_ms, 100) ms`, then sends
`release` with `timestamp` set to the elapsed milliseconds. Both frames are
sent via `notify` — awaiting a reply would deadlock until the request
timeout.

`action` is a **JSON-encoded string** whose inner `command` value must
match the `action.command` the hub published in its own config for that
function — **not** the human-facing `function.name`. For example, LG TV's
`Number1` function has `action.command = "1"`. Sending the function name
yields a hub error frame:

```json
{"code": 566, "msg": "Command not found for device id:78652298"}
```

To honour this, `Device` carries a `command_actions: dict[str, str]` map
populated from each `function.action.command` at config-parse time
(`harmonyhub/client.py:_parse_config`). `send_command(device, name, ...)`
looks the mapping up before building the action JSON; if a function is
missing from the map the name is used as a fallback. Users hitting
`code 566` should run `harmony config pull` and inspect the device's
`controlGroup[*].function[*].action` strings to spot the actual IR
command names.

### Volume repeat

`[volume]` in `config.toml` only affects the `volume_up` / `volume_down`
logical keys routed via `harmony key`. `mute` is always a single press.
Direct `harmony send --command VolumeUp` is also single-shot. The lib
loops `send_command` `repeat` times with `inter_press_delay_ms` between
presses (`harmonyhub/client.py:_send_repeated`). Use this when an AVR's
IR step is finer than the desired user step — e.g. set `repeat = 4` for
Yamaha receivers that move 0.5 dB per IR pulse.

## 4. Event shape

Spontaneous notifications look like this (no `id`):

```json
{
  "type": "connect.stateDigest?notify",
  "data": { "activityId": "100", "configVersion": 7 }
}
```

`startActivityFinished` events update `ActivityStatus.transition_state` from
`starting` to `started`.

## 5. Errors and edge cases

- A 200 HTTP response with `"code": "404"` from provisioning means the hub did
  not recognise the command and is treated as a `ProvisioningError`.
- A WebSocket close mid-request causes pending futures to surface as
  `HubUnavailableError("WebSocket closed: ...")`. The persistent supervisor
  reconnects; on-demand mode surfaces the error directly.
- Timeouts on individual requests raise `ProtocolError`. The connection itself
  is not torn down — the timeout is local to the call.
- `holdAction` returns no correlated reply. Awaiting one would always time
  out — use `transport.notify(...)`.
- Sending an `action.command` that doesn't match the hub's stored value
  yields `code: 566 "Command not found for device id:<id>"` as a spontaneous
  frame (no correlated id). Fix the lookup, not the transport.
