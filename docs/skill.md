# Natural-language skill — `harmonyhub`

The repo ships an agent skill at
[`../skill/harmonyhub/SKILL.md`](../skill/harmonyhub/SKILL.md) that turns
voice-style commands into hub actions. It is designed for Claude Code,
Claude Desktop, or any agent runtime that loads skill files.

The model translates the user's words into either an MCP tool call (when
`harmony-mcp` is wired up) or a shell call to the `harmony` CLI. Replies
stay short and human — no tool names, no JSON.

## What it covers

| Intent                  | Examples                                              | Action                                                                 |
| ----------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------- |
| Switch to a TV channel  | *"schalte Pro7 ein"*, *"watch ARD"*, *"Sat1 bitte"*   | activity → `Fernsehen`, then `harmony_set_channel`                     |
| Change activity         | *"Apple TV"*, *"Musik hören"*, *"Fernsehen"*          | `harmony_start_activity("<label>")`                                    |
| Turn everything off     | *"alles aus"*, *"Feierabend"*, *"power off"*          | `harmony_power_off`                                                    |
| Volume up / down        | *"lauter"*, *"leiser"*, *"louder"*, *"quieter"*       | `harmony_send_key("volume_up")` / `volume_down`                        |
| Mute                    | *"stumm"*, *"mute"*, *"Ton aus"*, *"Ton an"*          | `harmony_send_key("mute")`                                             |
| Channel ±               | *"nächster Sender"*, *"channel up"*, *"zurück zappen"*| `harmony_send_key("channel_up")` / `channel_down`                      |
| OK / Back               | *"OK"*, *"zurück"*, *"Menü"*                          | `harmony_send_key("ok")` / `back`                                      |
| Channel by number       | *"Kanal 11"*, *"channel 23"*                          | `harmony_set_channel("<n>")`                                           |
| What's on?              | *"was läuft"*, *"current activity"*                   | `harmony_get_status`                                                   |

## Hard rules

1. **Channel requests require the `Fernsehen` activity.** Before any
   `harmony_set_channel` (or `harmony channel`) call, the skill runs
   `harmony_get_status` and verifies
   `current_activity.activity_label == "Fernsehen"`. If anything else
   (incl. `PowerOff`, `Apple TV sehen`, `Musik hören`, `TV`) is active, it
   first starts `Fernsehen`, waits ~5 s for TV + AVR to come up, then sets
   the channel. The check is never skipped.
2. **Channel names are resolved via the built-in map** (see SKILL.md).
   Unknown names trigger a clarification question, never a guess.
3. Reply in one short sentence in the user's language. No tool names, no
   JSON.

## Channel-name → number map

The skill ships with a German-language map covering the main free-to-air
networks plus the public regionals. Examples:

| Channel | Names                       |
| ------- | --------------------------- |
| 1       | ARD, Das Erste, Erstes      |
| 2       | ZDF, Zweites                |
| 3       | RTL, RTL Television         |
| 4       | Sat1, Sat.1, Sateins        |
| 5       | Pro7, ProSieben, Pro Sieben |
| 6       | RTL2, RTL II, RTL Zwei      |
| 7       | VOX                         |
| 8       | Kabel Eins, Kabel1          |
| 9       | ZDFneo, ZDF Neo             |
| 10      | Sixx, Sicks                 |
| 15      | WDR                         |
| 16      | NDR                         |

Full list in [`../skill/harmonyhub/SKILL.md`](../skill/harmonyhub/SKILL.md).
The user can extend it at runtime (*"speicher VOX als 7"*).

## Activity labels on this hub

- **Fernsehen** — TV (Pro7/ARD/etc. live)
- **Apple TV sehen** — Apple TV
- **Musik hören** — Sonos / receiver music
- **TV** — secondary TV-only activity
- **PowerOff** — everything off (also via `harmony_power_off`)

Loose matching is expected: *"mach Apple TV an"* → `Apple TV sehen`,
*"Musik"* → `Musik hören`.

## Installing the skill

### Claude Code

Symlink (or copy) the skill folder into your global skills directory:

```bash
ln -s "$(pwd)/skill/harmonyhub" ~/.claude/skills/harmonyhub
```

The skill autoloads when you mention Harmony / channels / volume in a
session. Trigger phrase: `/harmonyhub`.

### Claude Desktop

Pair the skill with the MCP server from the main README so the model can
actually fire commands:

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

### CLI fallback

If MCP isn't wired up, the skill calls the CLI directly. Example for
*"schalte Pro7 ein"*:

```bash
harmony activities current | grep -qi Fernsehen \
  || (harmony activities start "Fernsehen" && sleep 5)
harmony channel 5
```

## When the model should say "no"

- Unknown channel name → ask which number and offer to add it.
- Ambiguous activity name → list the recognised labels and ask which.
- The hub returns `code 566` ("Command not found") → surface it plainly
  and suggest `harmony config pull` to inspect the IR command names.

See [`troubleshooting.md`](troubleshooting.md) for the common hub-side
failure modes.
