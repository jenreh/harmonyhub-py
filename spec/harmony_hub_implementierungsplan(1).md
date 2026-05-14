# Harmony Hub Python Library – Konzept & Implementierungsplan

> **Projektname:** `harmonyhub-py`
> **Paketname:** `harmony_local`
> **Stand:** Mai 2026
> **Ziel:** Lokale Steuerung des Logitech Harmony Hub via Python – nutzbar als Library, CLI und MCP-Server

---

## 1. Konzept & Protokoll-Grundlagen

### 1.1 Transportprotokolle

| Protokoll | Port | Verfügbarkeit | Authentifizierung |
|-----------|------|---------------|-------------------|
| **WebSocket** (primär) | `8088` | Immer aktiv, kein Setup nötig | `Origin`-Header + Remote-ID |
| **XMPP** (optionaler Fallback) | `5222` | Muss in Harmony App aktiviert werden | Session-Token via Logitech-Cloud |

**Strategie:** WebSocket als Default. XMPP nur als Fallback, weil es am Hub explizit aktiviert werden muss, historisch durch Firmware-Änderungen betroffen war und die initiale Authentifizierung einen Cloud-Schritt erfordert. WebSocket auf Port 8088 ist vollständig lokal.

### 1.2 WebSocket-Protokoll

#### Schritt 1: Hub-Informationen abrufen (HTTP POST, einmalig)

```
POST http://<HUB_IP>:8088/
Headers:
  Origin: http://sl.dhg.myharmony.com
  Content-Type: application/json
  Accept: application/json
  Accept-Charset: utf-8
Body:
  {"id": 1, "cmd": "setup.account?getProvisionInfo", "params": {}}

Response:
  {
    "data": {
      "activeRemoteId": "12345678",
      "accountId": "...",
      "email": "...",
      "discoveryServer": "svcs.myharmony.com"
    },
    "code": "200"
  }
```

`activeRemoteId` und `discoveryServer` (Domain) werden aus der Antwort extrahiert und lokal gecacht.

#### Schritt 2: WebSocket verbinden

```
ws://<HUB_IP>:8088/?domain=<discoveryServer>&hubId=<activeRemoteId>
```

#### Schritt 3: Nachrichtenformat

```json
{
  "hubId": "<activeRemoteId>",
  "timeout": 30,
  "hbus": {
    "cmd": "vnd.logitech.harmony/vnd.logitech.harmony.engine?<COMMAND>",
    "id": "<uuid-message-id>",
    "params": { "verb": "get", "format": "json" }
  }
}
```

Antworten kommen asynchron und werden anhand der `id` mit dem ausstehenden Request korreliert. Spontane Events (ohne `id`-Korrelation) werden separat behandelt.

#### Schritt 4: Keepalive

⚠️ Der Hub schließt die Verbindung nach **60 Sekunden** ohne Aktivität.
→ Ping/Heartbeat alle 50 Sekunden im persistenten Modus. Auto-Reconnect mit Exponential Backoff.

### 1.3 Relevante Befehle

| Zweck | Kommando |
|-------|---------|
| Hub-/Account-/Remote-ID abrufen | `setup.account?getProvisionInfo` via HTTP POST |
| Konfiguration abrufen | `vnd.logitech.harmony/vnd.logitech.harmony.engine?config` |
| Aktuelle Aktivität abfragen | `vnd.logitech.harmony/vnd.logitech.harmony.engine?getCurrentActivity` |
| Statusdigest abrufen | `vnd.logitech.connect/vnd.logitech.statedigest?get` |
| Aktivität starten | `vnd.logitech.harmony/vnd.logitech.harmony.engine?startactivity` |
| Aktivität starten (Fallback) | `harmony.activityengine?runactivity` |
| Taste senden | `vnd.logitech.harmony/vnd.logitech.harmony.engine?holdAction` |
| Kanal setzen | `harmony.engine?changeChannel` (Fallback: Ziffernfolge + Enter) |
| Sync auslösen | `setup.sync` |

### 1.4 Status-Einschränkungen

| Status-Frage | Verlässlichkeit | Konsequenz |
|---|---|---|
| Welche Activity ist aktiv? | ✅ Zuverlässig via `getCurrentActivity` und Events | Nativ abfragbar |
| Activity-Übergangsfortschritt | ✅ Via `startActivityFinished`-Event mit Zwischenstates | `transition_state` im Modell |
| Supplementärer Hub-Zustand | ⚠️ Via `statedigest?get`, Verfügbarkeit firmware-abhängig | Optionale Statusergänzung |
| Welcher Kanal? | ❌ Hub kennt keinen Kanalstatus | `last_channel` lokal tracken, Quelle ausweisen |
| Ist Gerät an/aus? | ❌ Nur so korrekt wie Harmony-Zustand | Aus aktiver Activity ableiten |
| Push-Events (Activity-Wechsel) | ✅ Hub sendet spontane Notifications | Via `AsyncIterator[HubEvent]` |

Wenn Geräte außerhalb von Harmony (Originalfernbedienung, HDMI-CEC, Gerät-App) geändert werden, weiß der Hub das nicht. Die Library behauptet keine falsche Telemetrie.

---

## 2. Architektur

### 2.1 Paketstruktur

```
harmonyhub-py/
│
├── harmony_local/
│   ├── __init__.py
│   ├── client.py              # HarmonyHubClient – zentrale High-Level-API
│   ├── models.py              # Frozen Dataclasses: HubInfo, Activity, Device, ...
│   ├── exceptions.py          # HubUnavailableError, ProvisioningError, ProtocolError, ...
│   ├── aliases.py             # Logische Tasten → Harmony-Kommandos + Fallback-Aliase
│   ├── status.py              # HubStatus-Verwaltung, last_channel-Persistenz
│   ├── cache.py               # Config-Cache (~/.cache/harmony-local/<hub-id>/)
│   ├── discovery.py           # mDNS/Bonjour + optionaler Subnetz-Scan
│   ├── protocol/
│   │   ├── __init__.py
│   │   ├── http.py            # getProvisionInfo, sync POST
│   │   ├── websocket.py       # WS-Verbindung, Request/Response-Korrelation, Events
│   │   └── xmpp.py            # Optionaler Fallback (nicht MVP)
│   ├── cli.py                 # Typer/Rich CLI
│   ├── mcp_server.py          # MCP Tools und Ressourcen
│   └── simulator.py           # Fake Hub für Tests
│
├── tests/
│   ├── unit/
│   │   ├── test_aliases.py
│   │   ├── test_config_parser.py
│   │   └── test_models.py
│   ├── integration/
│   │   └── test_real_hub.py   # opt-in via HARMONY_HUB_HOST env
│   └── conftest.py            # Simulator-Fixtures
│
├── docs/
│   ├── protocol.md            # Genutzte lokale Payloads
│   ├── routing.md             # Device-Routing-Beispiele
│   └── troubleshooting.md     # Häufige Probleme
│
└── pyproject.toml
```

### 2.2 Konfigurationspfade

| Zweck | Pfad |
|-------|------|
| Benutzerkonfiguration | `~/.config/harmony-local/config.toml` (Linux/macOS) |
| | `%APPDATA%\harmony-local\config.toml` (Windows) |
| Hub-Config-Cache | `~/.cache/harmony-local/<hub-id>/config.json` |
| Laufzeitstatus (`last_channel` etc.) | `~/.cache/harmony-local/<hub-id>/state.json` |

### 2.3 Konfigurationsdatei (TOML)

```toml
[hub]
host = "192.168.178.50"
# remote_id wird automatisch ermittelt und gecacht

[connection]
mode = "persistent"          # persistent | ondemand
protocol = "websocket"       # websocket | xmpp
keepalive_interval_s = 50
request_timeout_s = 10

[channel]
mode = "digits_then_enter"   # digits_then_enter | change_channel
inter_digit_delay_ms = 150
send_enter = true

[activity_routes."Fernsehen"]
volume_device = "Denon AVR"
channel_device = "Vodafone Receiver"
navigation_device = "Vodafone Receiver"
number_device = "Vodafone Receiver"

[activity_routes."Apple TV"]
volume_device = "Denon AVR"
navigation_device = "Apple TV"
number_device = "Apple TV"
```

**Konfigurationspriorität:** CLI-Argument > Umgebungsvariable > Config-Datei > Default

```bash
HARMONY_HUB_HOST=192.168.178.50
HARMONY_PROTOCOL=websocket
HARMONY_CONNECTION_MODE=persistent
```

---

## 3. Datenmodelle

```python
@dataclass(frozen=True)
class HubInfo:
    host: str
    remote_id: str
    account_id: str | None
    email_redacted: str | None      # Nur erste 2 Zeichen + Domain
    discovery_server: str | None
    firmware_version: str | None
    friendly_name: str | None

@dataclass(frozen=True)
class Activity:
    id: str
    label: str
    is_power_off: bool = False      # True wenn id == "-1"

@dataclass(frozen=True)
class Device:
    id: str
    label: str
    manufacturer: str | None
    model: str | None
    commands: tuple[str, ...]       # Alle verfügbaren IR-Kommandos

@dataclass(frozen=True)
class ActivityStatus:
    activity_id: str
    activity_label: str | None
    transition_state: str | None    # "starting", "started", None

@dataclass(frozen=True)
class HubStatus:
    current_activity: ActivityStatus
    last_channel: str | None
    last_channel_source: Literal["library", "harmony", "unknown"]
    connected: bool
    config_version: int | None

@dataclass(frozen=True)
class CommandResult:
    device_id: str
    command: str
    success: bool
    error: str | None = None

@dataclass(frozen=True)
class ChannelResult:
    channel: str
    method: str                     # "change_channel" | "digits_then_enter"
    success: bool
    error: str | None = None

@dataclass(frozen=True)
class HubEvent:
    type: str
    data: dict
    raw: dict
```

---

## 4. Core Client API

```python
class HarmonyHubClient:
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    # Hub-Informationen
    async def get_info(self) -> HubInfo: ...

    # Konfiguration
    async def get_config(self, refresh: bool = False) -> HubConfig: ...
    async def list_activities(self) -> list[Activity]: ...
    async def list_devices(self) -> list[Device]: ...
    async def list_device_commands(self, device: str | int) -> list[str]: ...

    # Status
    async def get_current_activity(self) -> ActivityStatus: ...
    async def get_status(self) -> HubStatus: ...

    # Event-Stream
    async def listen(self) -> AsyncIterator[HubEvent]: ...

    # Aktivitäten
    async def start_activity(self, activity: str | int) -> ActivityStatus: ...
    async def power_off(self) -> ActivityStatus: ...

    # Geräte
    async def device_power_on(self, device: str | int) -> CommandResult: ...
    # Sucht zuerst PowerOn, Fallback auf PowerToggle (konfigurierbar)
    async def device_power_off(self, device: str | int) -> CommandResult: ...

    # Befehle
    async def send_command(
        self, device: str | int, command: str, hold_ms: int = 0
    ) -> CommandResult: ...
    # hold_ms=0 → press + kurze Pause + release
    # hold_ms>0 → press + hold_ms + release

    # Logische Tasten (mit Alias-Resolver und Activity-Routing)
    async def send_key(
        self,
        key: LogicalKey,
        device: str | int | None = None,
        activity: str | None = None,
    ) -> CommandResult: ...

    # Kanal
    async def set_channel(
        self, channel: str | int, device: str | int | None = None
    ) -> ChannelResult: ...
```

### 4.1 Verbindungsmodi

```
PERSISTENT:                           ON-DEMAND:
┌────────────────────┐                ┌────────────────────┐
│  connect()         │─► offen        │  async with client │
│  Ping alle 50s     │   gehalten     │    as hub:         │
│  Auto-Reconnect    │   Backoff bei  │      ...           │
│  bei Disconnect    │   Fehler       │  Verbindung auto.  │
└────────────────────┘                │  auf/abgebaut      │
                                      └────────────────────┘
```

---

## 5. Alias-Resolver

Die Library mappt **logische Tasten** auf gerätespezifische Harmony-IR-Kommandos. Da Kommandonamen je Gerätehersteller variieren, wird eine Fallback-Kette durchsucht:

| Logische Taste | Primär | Fallbacks |
|---|---|---|
| `volume_up` | `VolumeUp` | `VolUp`, `Volume+` |
| `volume_down` | `VolumeDown` | `VolDown`, `Volume-` |
| `channel_up` | `ChannelUp` | `Channel+`, `ProgramUp`, `ChannelNext` |
| `channel_down` | `ChannelDown` | `Channel-`, `ProgramDown`, `ChannelPrev` |
| `digit_0`–`digit_9` | `0`–`9` | `Number0`–`Number9`, `Digit0`–`Digit9`, `Num0`–`Num9` |
| `ok` / `enter` | `OK` | `Enter`, `Select`, `DirectionSelect` |
| `back` | `Back` | `Return`, `Exit`, `PreviousMenu`, `DirectionBack` |
| `off` | Activity `-1` | Gerätebefehl `PowerOff` nur bei explizitem Device-Ziel |

**Routing-Logik:**
1. Explizit übergebenes `device`-Argument → direkt verwenden.
2. TOML-Routing für aktive Activity → konfigurierten Device wählen.
3. Eindeutiger Treffer im Aktivitätskontext → automatisch wählen.
4. Mehrdeutigkeit → `AmbiguousRoutingError` mit Kandidatenliste.

---

## 6. Kanalsteuerung

Zwei Modi, konfigurierbar in `config.toml`:

**Modus `change_channel`:** Sendet den nativen Hub-Befehl `harmony.engine?changeChannel`.

**Modus `digits_then_enter` (Default):** Sendet Ziffern einzeln mit konfigurierbarem `inter_digit_delay_ms`, optional gefolgt von `OK`/`Enter`.

```python
result = await client.set_channel("101")
# result.method == "digits_then_enter"
# status.last_channel == "101"
# status.last_channel_source == "library"
```

---

## 7. CLI-Interface

Technologie: **Typer** + **Rich** für formatierte Ausgabe.

```bash
# Discovery und Setup
harmony discover                          # mDNS-Suche im Netzwerk
harmony info --host 192.168.178.50        # Hub-Informationen anzeigen
harmony config pull --host 192.168.178.50 --out config.json
harmony doctor                            # Diagnose: Host/Port/WS/Config/Routing

# Aktivitäten
harmony activities list
harmony activities current
harmony activities start "Fernsehen"
harmony power-off

# Geräte
harmony devices list
harmony devices commands "Denon AVR"
harmony device power-on "LG TV"
harmony device power-off "LG TV"

# Tasten
harmony key volume-up [--device "Denon AVR"]
harmony key volume-down
harmony key channel-up
harmony key channel-down
harmony key digit 1 [--device "Receiver"]
harmony key ok
harmony key back

# Kanal
harmony channel set 101 [--device "Receiver"]

# Direktbefehl (Debugging)
harmony send --device "Samsung TV" --command "VolumeUp"

# Status und Monitoring
harmony status
harmony listen                            # Eventstream ausgeben (Strg+C zum Beenden)
```

### CLI-Designregeln

- Alle Befehle akzeptieren `--host` (überschreibt Config-Datei).
- `--json` für maschinenlesbare Ausgabe bei allen relevanten Befehlen.
- `--device` und `--activity` für explizites Routing.
- **Alle Logs gehen auf `stderr`** – niemals auf `stdout` (MCP/STDIO-Kompatibilität).
- Fehlermeldungen enthalten konkrete Geräte-/Command-Kandidaten.

### CLI Exit-Codes

| Code | Bedeutung |
|------|-----------|
| `0` | Erfolg |
| `2` | Usage-/Validierungsfehler |
| `10` | Hub nicht erreichbar |
| `11` | Protokollfehler |
| `12` | Kommando/Alias nicht gefunden |
| `13` | Routing mehrdeutig |

---

## 8. MCP-Server

Technologie: **Offizielles MCP Python SDK** (`mcp`).
Default-Transport: **stdio** (lokal, sicher).
Optional: Streamable HTTP – nur mit Authentifizierung und ohne `0.0.0.0`-Binding.

### 8.1 MCP Tools

| Tool | Beschreibung |
|------|-------------|
| `harmony_get_status` | Aktuelle Activity, Verbindung, `last_channel`, Quelle |
| `harmony_list_activities` | Alle konfigurierten Activities |
| `harmony_start_activity` | Activity per Name oder ID starten |
| `harmony_power_off` | PowerOff-Activity starten |
| `harmony_list_devices` | Alle konfigurierten Geräte |
| `harmony_list_device_commands` | Verfügbare Commands eines Geräts |
| `harmony_device_power_on` | Gerät einschalten (`PowerOn` / Fallback `PowerToggle`) |
| `harmony_device_power_off` | Gerät ausschalten (`PowerOff`) |
| `harmony_send_key` | Logische Taste senden |
| `harmony_send_command` | Rohes Harmony-Kommando senden |
| `harmony_set_channel` | Kanal setzen, `last_channel` aktualisieren |
| `harmony_refresh_config` | Hub-Config neu laden |

```python
@mcp.tool()
async def harmony_send_key(
    key: Literal[
        "volume_up", "volume_down", "channel_up", "channel_down",
        "digit_0", "digit_1", "digit_2", "digit_3", "digit_4",
        "digit_5", "digit_6", "digit_7", "digit_8", "digit_9",
        "ok", "enter", "back", "off"
    ],
    device: str | None = None,
    activity: str | None = None,
) -> dict: ...
```

### 8.2 MCP Resources

| Resource URI | Inhalt |
|---|---|
| `harmony://config` | Normalisierte Hub-Config (Activities + Devices) |
| `harmony://activities` | Aktivitätenliste mit IDs |
| `harmony://devices` | Geräteliste mit Commands |
| `harmony://status` | Aktueller Status inkl. `last_channel` |

### 8.3 Claude Desktop Integration

```json
// ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "harmony": {
      "command": "harmony-mcp",
      "args": [],
      "env": {
        "HARMONY_HUB_HOST": "192.168.178.50"
      }
    }
  }
}
```

### 8.4 MCP-Sicherheitsregeln

- **Kein Logging auf stdout** – bricht das STDIO-Protokoll.
- Nicht auf `0.0.0.0` binden (Default stdio braucht das nicht).
- Keine Account-ID, vollständige E-Mail oder Provisioning-Rohdaten in Tool-Antworten.
- Destruktive Aktionen (`power_off`, `start_activity`) in Tool-Descriptions klar beschreiben.
- Keine Shell-Kommandos aus Tool-Parametern ableiten.

---

## 9. Implementierungsphasen

### Phase 0 – Projekt-Setup

**Ziel:** Reproduzierbares Python-Package mit sauberer Trennung Core / CLI / MCP.

| # | Aufgabe | Details |
|---|---------|---------|
| 0.1 | Repository + `pyproject.toml` | Python ≥ 3.11, Entry Points, optionale XMPP-Extra |
| 0.2 | Paketstruktur anlegen | Alle Module als leere Dateien mit Docstrings |
| 0.3 | Tooling konfigurieren | `ruff`, `mypy`, `pytest`, `pytest-asyncio` |
| 0.4 | Config-Pfade implementieren | XDG-konforme Pfade, plattformübergreifend |
| 0.5 | Entry Points prüfen | `harmony --help`, `harmony-mcp --help` |

**Akzeptanzkriterium:** `pip install -e .` (oder `uv pip install -e .`) funktioniert, `pytest` läuft fehlerfrei ohne Tests.

### Phase 1 – HTTP Provisioning

**Ziel:** Hub-Informationen lokal abrufen und validieren.

| # | Aufgabe | Details |
|---|---------|---------|
| 1.1 | `protocol/http.py` | POST auf Port 8088 mit korrekten Headern |
| 1.2 | Response normalisieren | `activeRemoteId`, `discoveryServer`, `accountId`, `email` redacted |
| 1.3 | `HubInfo` befüllen | `firmware_version`, `friendly_name` extrahieren sofern vorhanden |
| 1.4 | Fehlerklassen | `HubUnavailableError`, `ProvisioningError`, `ProtocolError` |
| 1.5 | Remote-ID cachen | In `~/.cache/harmony-local/<hub-id>/config.json` |

**Akzeptanzkriterium:** `harmony info --host <ip> --json` gibt Remote-ID und redacted Hub-Infos aus. Fehler bei nicht erreichbarem Hub ist klar.

### Phase 2 – WebSocket-Verbindung

**Ziel:** Stabile WebSocket-Kommunikation mit Message-ID-Korrelation.

| # | Aufgabe | Details |
|---|---------|---------|
| 2.1 | `protocol/websocket.py` | WebSocket-URL aus Provisioning-Daten bauen |
| 2.2 | Request-Korrelation | UUID pro Request, `pending_requests: dict[str, Future]` |
| 2.3 | Event-Separation | Notifications/Events ohne `id` separat via Queue |
| 2.4 | Keepalive | Ping-Task alle 50s im persistenten Modus |
| 2.5 | Auto-Reconnect | Exponential Backoff, Reconnect-Events emittieren |
| 2.6 | `listen()` | `AsyncIterator[HubEvent]` für den Event-Stream |
| 2.7 | Sauberes `close()` | Pending Futures cancelln, Tasks stoppen |

**Akzeptanzkriterium:** Verbindung bleibt >60s stabil. Disconnect/Reconnect wird erkannt. Responses und Events werden nicht vermischt.

### Phase 3 – Konfigurationsabruf und Normalisierung

**Ziel:** Activities, Devices und Device-Commands laden und cachen.

| # | Aufgabe | Details |
|---|---------|---------|
| 3.1 | `get_config()` via `?config` | Raw-Response normalisieren |
| 3.2 | Activities extrahieren | `data.activity[]` → `list[Activity]` |
| 3.3 | Devices extrahieren | `data.device[]` → `list[Device]` |
| 3.4 | Commands extrahieren | `controlGroup[].function[].action` → `tuple[str, ...]` |
| 3.5 | Cache schreiben | `config.json` + Config-Version merken |
| 3.6 | `cache.py` | Cache-Invalidierung nach TTL oder explizitem Refresh |

**Akzeptanzkriterium:** `harmony activities list`, `harmony devices list`, `harmony devices commands <device>` zeigen korrekte Daten.

### Phase 4 – Aktivitätssteuerung

**Ziel:** Activities starten, PowerOff, aktuellen Status erkennen.

| # | Aufgabe | Details |
|---|---------|---------|
| 4.1 | `get_current_activity()` | `getCurrentActivity` → `ActivityStatus` |
| 4.2 | `get_status()` | `getCurrentActivity` + `statedigest?get` (optional) + Cache |
| 4.3 | `start_activity()` | Per Name (fuzzy match) oder ID |
| 4.4 | `power_off()` | `start_activity("-1")` |
| 4.5 | Event `startActivityFinished` | `transition_state` im `ActivityStatus` aktualisieren |
| 4.6 | Fallback-Kommando | `harmony.activityengine?runactivity` als Secondary Try |
| 4.7 | Idempotenz | Bereits aktive Activity erkennen und behandeln |

**Akzeptanzkriterium:** `harmony activities current`, `harmony activities start <name>`, `harmony power-off` funktionieren.

### Phase 5 – Device Commands und Tastendrücke

**Ziel:** Gerätebefehle senden, alle geforderten logischen Tasten unterstützen.

| # | Aufgabe | Details |
|---|---------|---------|
| 5.1 | `send_command()` | `holdAction` mit press + Pause + release |
| 5.2 | `hold_ms`-Unterstützung | press → wait hold_ms → release |
| 5.3 | `aliases.py` | Fallback-Kette pro logischer Taste |
| 5.4 | `send_key()` | Alias-Resolver + Routing-Logik |
| 5.5 | Activity-Routing | `[activity_routes]` aus TOML |
| 5.6 | `device_power_on()` | `PowerOn` → Fallback `PowerToggle` (konfigurierbar) |
| 5.7 | `device_power_off()` | `PowerOff` |
| 5.8 | `AmbiguousRoutingError` | Mit Kandidatenliste |

**Akzeptanzkriterium:** `harmony key volume-up --device <device>`, `harmony key digit 5`, `harmony key ok` funktionieren. Mehrdeutigkeit liefert hilfreichen Fehler.

### Phase 6 – Kanalsteuerung und Kanalstatus

**Ziel:** Kanäle setzen, Status ehrlich verwalten.

| # | Aufgabe | Details |
|---|---------|---------|
| 6.1 | `set_channel()` | `change_channel`-Modus oder `digits_then_enter`-Modus |
| 6.2 | Inter-Digit-Delay | Konfigurierbar, Default 150ms |
| 6.3 | `status.py` | `last_channel` + `last_channel_source` in `state.json` persistieren |
| 6.4 | Statusehrlichkeit | `source == "library"` wenn über diese Library gesetzt |

**Akzeptanzkriterium:** `harmony channel set 101` sendet korrekte Sequenz. `harmony status` zeigt `last_channel` mit Quelle. Dokumentation erklärt Grenzen.

### Phase 7 – CLI

**Ziel:** Vollständiges lokales Bedienwerkzeug, scriptbar.

| # | Aufgabe | Details |
|---|---------|---------|
| 7.1 | Typer-App strukturieren | Subcommands, `--host`, `--json`, `--device` global |
| 7.2 | Alle Kommandogruppen | `discover`, `info`, `config`, `activities`, `devices`, `device`, `key`, `channel`, `status`, `listen` |
| 7.3 | `harmony doctor` | Prüft: Host erreichbar → Port 8088 → Provisioning → WebSocket → Config → Activity → Routing |
| 7.4 | Exit-Codes | 0 / 2 / 10 / 11 / 12 / 13 |
| 7.5 | Logs auf stderr | Niemals auf stdout |
| 7.6 | Rich-Output | Tabellen für Listen, farbige Status-Badges |

**Akzeptanzkriterium:** Alle Funktionen per CLI erreichbar, `--json` funktioniert überall, `harmony doctor` gibt klare Pass/Fail-Diagnose aus.

### Phase 8 – MCP-Server

**Ziel:** Alle Funktionen als MCP Tools und Resources bereitstellen.

| # | Aufgabe | Details |
|---|---------|---------|
| 8.1 | `mcp_server.py` | Offizielles MCP Python SDK, `HarmonyHubClient`-Singleton |
| 8.2 | STDIO-Transport | Default, keine weiteren Abhängigkeiten |
| 8.3 | Alle Tools implementieren | Siehe Tabelle in Abschnitt 8.1 |
| 8.4 | Alle Resources implementieren | `harmony://config`, `harmony://activities`, `harmony://devices`, `harmony://status` |
| 8.5 | Kein stdout-Logging | Alle Logs via `logging` auf stderr |
| 8.6 | Tool-Outputs | Kurz, strukturiert, JSON-kompatibel, keine sensiblen Daten |

**Akzeptanzkriterium:** MCP Inspector listet und ruft Tools auf. Claude Desktop kann Activities starten und Tasten senden. Kein Protokollbruch durch stdout-Logging.

### Phase 9 – Tests

**Ziel:** Hohe Testbarkeit ohne echten Hub, opt-in Integrationstests.

| # | Aufgabe | Details |
|---|---------|---------|
| 9.1 | `simulator.py` | Fake Hub: HTTP Provisioning + WebSocket Endpoint mit konfigurierbaren Antworten |
| 9.2 | Simulator-Fixtures | `startActivityFinished`-Event, Config-Response, holdAction-Response |
| 9.3 | Unit-Tests | Alias-Resolver, Config-Parser, Activity/Device Lookup, Fehlerfälle |
| 9.4 | Integrationstests (opt-in) | `HARMONY_HUB_HOST=... pytest -m integration` |
| 9.5 | CLI Snapshot-Tests | Typer-Testclient, Ausgabe-Snapshots |
| 9.6 | MCP Tool-Tests | MCP SDK-Testclient |

**Akzeptanzkriterium:** Unit-Test-Coverage für Parser/Resolver hoch. Kein echter Hub für CI nötig. Echte-Hub-Tests zerstörungsarm und opt-in.

### Phase 10 – Dokumentation

**Ziel:** Nutzbare Doku für Installation, Setup, Debugging und Grenzen.

| # | Aufgabe | Details |
|---|---------|---------|
| 10.1 | `README.md` | Installation, Quick-Start, CLI-Beispiele, MCP-Einrichtung, Statusgrenzen |
| 10.2 | `docs/protocol.md` | Alle genutzten lokalen Payloads mit Beispielen |
| 10.3 | `docs/routing.md` | Device-Routing-Beispiele für typische Setups |
| 10.4 | `docs/troubleshooting.md` | Hub nicht erreichbar, Port 8088 blockiert, WS-Abbruch, Befehl nicht gefunden, Kanalstatus-Grenzen |
| 10.5 | Security-Hinweise | Lokale Nutzung, MCP-Transport-Risiken |

**Akzeptanzkriterium:** Neuer Nutzer kann Hub-IP eintragen, Config lesen, Activity starten und Taste senden – nur anhand der Doku.

---

## 10. Abhängigkeiten

```toml
[project]
name = "harmonyhub-py"
requires-python = ">=3.11"

dependencies = [
    "httpx>=0.27",          # Async HTTP für Provisioning
    "websockets>=12.0",     # WebSocket-Verbindung
    "mcp>=1.0",             # Offizielles MCP Python SDK
    "typer[all]>=0.12",     # CLI mit Rich-Output
    "pydantic>=2.0",        # Datenmodelle & Validierung
    # tomllib ist ab Python 3.11 in der Standardbibliothek
]

[project.optional-dependencies]
xmpp = ["slixmpp>=1.8"]    # Optionaler XMPP-Transport

[tool.pytest.ini_options]
asyncio_mode = "auto"

[project.scripts]
harmony = "harmony_local.cli:app"
harmony-mcp = "harmony_local.mcp_server:main"
```

---

## 11. Risiken und Gegenmaßnahmen

| Risiko | Auswirkung | Gegenmaßnahme |
|--------|------------|---------------|
| Lokale API nicht offiziell stabil | Firmware-Update kann Verhalten ändern | Protokoll-Abstraktion, Fallback-Kommandos, klare Fehlerdiagnose |
| WebSocket-Verbindung bricht ab | Sporadisch fehlgeschlagene Befehle | Keepalive, Auto-Reconnect mit Backoff, Retry für idempotente Abfragen |
| Mehrere Geräte bieten gleiche Commands | Falsches Gerät erhält Taste | Activity-Routing-Config, explizites `--device`, `AmbiguousRoutingError` |
| Physischer Gerätezustand driftet | Status zeigt falsches Bild | Keine falsche Telemetrie behaupten, `harmony sync` empfehlen |
| Kanal außerhalb Library geändert | `last_channel` veraltet | `last_channel_source` ausweisen, Grenzen klar dokumentieren |
| MCP-Server remote exponiert | Unautorisierte Steuerung | Default stdio, kein `0.0.0.0`, Auth für HTTP-Transport |
| Account-/Hub-Daten in Logs | Datenschutzproblem | E-Mail redacted, keine Account-ID in Tool-Antworten |
| Concurrent Requests | Falsche Response-Zuordnung | UUID-basierte `msg_id`, Timeout-basiertes Cleanup |

---

## 12. MVP-Scope

**Im MVP enthalten:**

1. Manuelle Hub-IP-Konfiguration
2. HTTP Provisioning (Remote-ID, Domain)
3. WebSocket-Verbindung (persistent + on-demand)
4. Hub-Config abrufen (Activities, Devices, Commands)
5. Activities listen / starten / PowerOff
6. Devices listen / Device-Commands listen
7. Tasten senden mit explizitem `--device`
8. Kanalsteuerung mit `last_channel`-Tracking
9. Status: aktuelle Activity + `last_channel` + Quelle
10. CLI für alle MVP-Funktionen inkl. `harmony doctor`
11. MCP STDIO Server mit allen Kern-Tools + Resources
12. Simulator für Tests ohne echten Hub

**Nicht im MVP:**

- Automatische mDNS-Discovery
- Vollständiger XMPP-Fallback
- Automatisches Device-Routing ohne TOML-Config
- Echte Kanal-Telemetrie
- Remote HTTP MCP Server
- Änderung der Harmony-Konfiguration am Hub
- Multi-Hub-Unterstützung

---

## 13. Beispiel-Nutzung (Library)

```python
import asyncio
from harmony_local import HarmonyHubClient

async def main():
    async with HarmonyHubClient("192.168.178.50", connection_mode="ondemand") as hub:
        # Hub-Info
        info = await hub.get_info()
        print(f"Hub: {info.friendly_name} (Remote-ID: {info.remote_id})")

        # Status
        status = await hub.get_status()
        label = status.current_activity.activity_label or "Aus"
        print(f"Aktive Activity: {label}")
        if status.last_channel:
            print(f"Letzter Kanal: {status.last_channel} (Quelle: {status.last_channel_source})")

        # Activities auflisten
        for activity in await hub.list_activities():
            print(f"  - {activity.label} (ID: {activity.id})")

        # TV starten
        await hub.start_activity("Fernsehen")

        # Lautstärke über Alias-Resolver + Activity-Routing aus config.toml
        await hub.send_key("volume_up")
        await asyncio.sleep(0.3)
        await hub.send_key("volume_down")

        # Kanal wechseln (digits_then_enter)
        result = await hub.set_channel("101")
        print(f"Kanal gesetzt via: {result.method}")

        # Event-Stream kurz beobachten
        async with asyncio.timeout(5):
            async for event in hub.listen():
                print(f"Event: {event.type} → {event.data}")

        # Alles aus
        await hub.power_off()

asyncio.run(main())
```

---

*Erstellt: Mai 2026 | Protokoll-Grundlage: Harmony Hub WebSocket API (Port 8088) + XMPP (Port 5222, optional)*
