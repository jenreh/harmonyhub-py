# Device routing — how logical keys pick a target device

The Harmony Hub has no opinion about which device a logical key (`volume_up`,
`channel_up`, `digit_5`, `ok`, …) belongs to. The library decides at call
time. Three layers of precedence apply.

## Precedence

1. **Explicit `--device` argument** — always wins. Skip routing entirely.
2. **`[activity_routes.<active-label>]` in `config.toml`** — for the
   currently-active activity, map each logical key family to a specific
   device.
3. **Single-candidate auto-pick** — if exactly one device in the hub config
   exposes a command from the alias chain, use it. Multiple candidates raise
   `AmbiguousRoutingError`; zero candidates raise `CommandNotFoundError`.

## Route fields

The TOML key per logical-key family:

| Logical-key family            | TOML field             |
| ----------------------------- | ---------------------- |
| `volume_up`, `volume_down`, `mute` | `volume_device`        |
| `channel_up`, `channel_down`  | `channel_device`       |
| `digit_0` … `digit_9`         | `number_device` (falls back to `channel_device`) |
| `ok`, `enter`, `back`         | `navigation_device`    |

## Example

A typical living-room setup where the Yamaha AVR handles audio, the Vodafone
cable receiver provides the numeric keypad and channel keys, and navigation
runs through the receiver too:

```toml
[activity_routes."Fernsehen"]
volume_device = "Yamaha AV-Empfänger"
channel_device = "Vodafone Receiver"
navigation_device = "Vodafone Receiver"
number_device = "Vodafone Receiver"

[activity_routes."Apple TV sehen"]
volume_device = "Yamaha AV-Empfänger"
navigation_device = "Apple TV"
number_device = "Apple TV"
```

With the above, `harmony key volume-up` while `Fernsehen` is active fires
IR at the AVR. While `Apple TV sehen` is active, the same command still
goes to the AVR — only navigation/numbers shift to the Apple TV.

## Common pitfalls

- **Device name not matching** — device labels are matched (in order) by id,
  exact case-insensitive label, then unique substring. `"Yamaha"` is unique
  enough; `"AV"` may match multiple devices.
- **Ambiguity** — multiple devices expose `Number1`. Either configure an
  `activity_routes` block for the active activity or pass `--device`.
- **`code 566` from the hub** — the command name in `Device.commands` is the
  hub's `function.name`, but the IR-fire instruction needs the inner
  `action.command`. The lib stores both in `Device.command_actions`; this is
  transparent to most callers but worth knowing when debugging.
