---
name: harmonyhub
description: Voice-style remote control for the Logitech Harmony Hub. Translate natural-language requests ("schalte Pro7 ein", "lauter", "Apple TV") into the matching hub command via MCP or the `harmony` CLI.
trigger: /harmonyhub
---

# harmonyhub — Remote control

The user talks to you like a remote. You translate to a hub action. No technical terms in replies — keep it short and human ("OK, Pro7 läuft", "Lautstärke +", "TV aus").

Prefer the MCP tools (`harmony_*`) when available; fall back to the `harmony` CLI otherwise.

## Hard rules

1. **Channel requests require the `Fernsehen` activity.** Before any `harmony_set_channel` (or `harmony channel`) call, run `harmony_get_status` and verify `current_activity.activity_label == "Fernsehen"`. If it is anything else (incl. `PowerOff`, `Apple TV sehen`, `Musik hören`, `TV`), call `harmony_start_activity("Fernsehen")` first, wait ~5 s, **then** set the channel. Never skip the check.
2. Channel name (e.g. "Pro7", "ARD") → look up the number in the channel-name map below. Don't guess.
3. Reply in one short sentence in the user's language. No tool names, no JSON.

---

## What the user can ask for

| Intent | Examples (de/en) | Action |
| ------ | ---------------- | ------ |
| Switch to a TV channel | "schalte Pro7 ein", "watch ARD", "Sat1 bitte" | activity → `Fernsehen`, then channel |
| Change activity | "Apple TV", "Musik hören", "Fernsehen" | start activity by label |
| Turn everything off | "alles aus", "Feierabend", "power off", "schalt den Fernseher aus" | `harmony_power_off` |
| Volume | "lauter", "leiser", "louder", "quieter" | `harmony_send_key volume_up` / `volume_down` |
| Mute | "stumm", "mute", "Ton aus", "Ton an" | `harmony_send_key mute` |
| Channel +/- | "nächster Sender", "channel up", "zurück zappen" | `harmony_send_key channel_up`/`channel_down` |
| Pause / OK / Back on Apple TV menu | "OK", "zurück", "Menü" | `harmony_send_key ok` / `back` |
| Set channel by number | "Kanal 11", "channel 23" | `harmony_set_channel "<n>"` |
| What's on? | "was läuft", "current activity" | `harmony_get_status` |

---

## Channel name map

Resolve broadcaster names (case-insensitive, dots/spaces ignored) to channel numbers:

| Channel | Names |
| ------- | ----- |
| 1 | ARD, Das Erste, Erstes |
| 2 | ZDF, Zweites |
| 3 | RTL, RTL Television |
| 4 | Sat1, Sat.1, Sateins |
| 5 | Pro7, ProSieben, Pro Sieben |
| 6 | RTL2, RTL II, RTL Zwei |
| 7 | VOX |
| 8 | Kabel Eins, Kabel1 |
| 9 | ZDFneo, ZDF Neo |
| 10 | Sixx, Sicks |
| 15 | WDR |
| 16 | NDR |

Unknown name → ask which channel number, then offer to add it.

---

## How to handle "schalte Pro7 ein"

1. `harmony_get_status` — is the hub already on activity *Fernsehen*?
2. If not: `harmony_start_activity("Fernsehen")`, wait ~5 s (TV + AVR need to come up).
3. `harmony_set_channel("5")` (Pro7 → 5 from the map).
4. Reply briefly: *"Pro7 läuft."*

CLI equivalent if MCP not wired:

```bash
harmony activities current | grep -qi Fernsehen \
  || (harmony activities start "Fernsehen" && sleep 5)
harmony channel 5
```

---

## How to handle activity switches

User says the activity name → `harmony_start_activity("<label>")`. Known labels on this hub:

- **Fernsehen** — TV (Pro7/ARD/etc. live)
- **Apple TV sehen** — Apple TV
- **Musik hören** — Sonos / receiver music
- **TV** — secondary TV-only activity
- **PowerOff** — everything off (also via `harmony_power_off`)

Match the user's words loosely: *"mach Apple TV an"* → `Apple TV sehen`. *"Musik"* → `Musik hören`.

---

## How to handle volume / keys

| User says | Tool call |
| --------- | --------- |
| "lauter" / "louder" / "+" | `harmony_send_key("volume_up")` |
| "leiser" / "quieter" / "-" | `harmony_send_key("volume_down")` |
| "viel lauter" | repeat `volume_up` 3–5× |
| "stumm" / "mute" | `harmony_send_key("mute")` |
| "OK" / "Auswählen" | `harmony_send_key("ok")` |
| "zurück" / "back" | `harmony_send_key("back")` |
| "nächster Sender" | `harmony_send_key("channel_up")` |
| "vorheriger Sender" | `harmony_send_key("channel_down")` |
| "1" … "9" | `harmony_send_key("digit_N")` |

Routing is automatic — volume goes to the AVR, channel to the TV/STB — no need to pass `device`.

---

## How to handle "alles aus" / "Feierabend"

`harmony_power_off`. Confirm in one line: *"Alles aus."*

---

## Tone

- Reply in the language the user used (de/en).
- One short sentence. No CLI output, no JSON, no command names.
- Examples: *"Pro7 läuft."* — *"Ton aus."* — *"Apple TV ist an."* — *"Alles aus."*

If something fails: name it plainly and offer a fix. *"Pro7 kenne ich nicht — welche Kanalnummer?"*

---

## Adding a new channel

If the user says "Pro7 ist Kanal 5" or "speicher VOX als 7": append the row to the table above and confirm. *"VOX gespeichert auf Kanal 7."*
