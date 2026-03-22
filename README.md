# Cricket Scoreboard

A digital LED cricket scoreboard driven by nine 64×64 HUB75 panels on a
Raspberry Pi 3B, with two scoring input paths:

1. **Play Cricket integration** — the PCS scorer app (Android/iOS tablet)
   sends ball-by-ball data over Bluetooth to the Pi, following the ECB's
   "Build your own scoreboard" community project.  Optionally, the Play
   Cricket web API can be polled for match summary data.
2. **Custom wireless remote** — an Adafruit ESP32-S3 Feather handset
   communicates with the Pi over BLE for manual scoring without the PCS app.

---

## Architecture

```
                  ┌──────────────────────┐
                  │  PCS Scorer App      │
                  │  (Android tablet)    │
                  └────────┬─────────────┘
                           │ Bluetooth (BespokeScore protocol)
                           ▼
                  ┌──────────────────────┐     HTTP (optional)
                  │  PlayCricketBridge   │◄──── Play Cricket
                  │  Python service      │      Web API v2
                  │  (Raspberry Pi 3B)   │
                  └────┬──────────┬──────┘
             BLE GATT  │          │ Unix socket / shared memory
                       │          │
          ┌────────────▼──┐  ┌────▼──────────────┐
          │ CricketRemote │  │  Raspscoreboard    │
          │ ESP32-S3      │  │  9× HUB75 64×64   │
          │ (handset)     │  │  192×192 px canvas │
          └───────────────┘  └────────────────────┘
```

### Data flow

| Source | Protocol | Receiver | Output |
|--------|----------|----------|--------|
| PCS app | Bluetooth Classic (SPP-like) | PlayCricketBridge | MatchState → display |
| Play Cricket web API | HTTPS JSON polling | PlayCricketBridge | MatchState → display |
| ESP32 remote | BLE GATT notify | PlayCricketBridge | Scoring commands → MatchState → display |
| PlayCricketBridge | Unix socket (JSON) | Raspscoreboard | Frame rendering |

---

## Subprojects

| Folder | Platform | Language | Purpose |
|--------|----------|----------|---------|
| `Raspscoreboard/` | Raspberry Pi 3B | C++ | HUB75 panel driver and renderer |
| `PlayCricketBridge/` | Raspberry Pi 3B | Python | Scoring bridge — PCS Bluetooth receiver, Play Cricket API client, BLE server for ESP32 remote |
| `CricketRemote/` | Adafruit ESP32-S3 Feather | C++ (Arduino) | Physical wireless scoring remote |

---

## Hardware Bill of Materials

| Component | Qty | Notes |
|-----------|-----|-------|
| Raspberry Pi 3B | 1 | Runs Raspscoreboard + PlayCricketBridge |
| 64×64 HUB75 LED panel | 9 | 3 parallel chains × 3 panels = 192×192 px |
| 5 V PSU (≥4 A per panel) | 1+ | Never power panels from Pi GPIO 5 V |
| Adafruit RGB Matrix Bonnet/HAT | 1 | Recommended over bare wiring |
| Adafruit ESP32-S3 Feather | 1 | 4 MB flash, 2 MB PSRAM |
| BTLE Mini board | 1 | Connects to Pi USB for BLE comms with remote |
| Tactile buttons / membrane keypad | 1 set | Mounted on remote handset |
| Android tablet | 1 | Running PCS scorer app (existing) |

---

## Display Layout (192×192 px)

Preliminary zone allocation for the 3×3 panel grid:

```
┌──────────────────────────────────────────────────┐
│  BATTING TEAM NAME                               │  row 0-20
├────────────────────┬─────────────────────────────┤
│                    │                             │
│   TOTAL            │   WICKETS     OVERS         │  row 21-90
│   (large digits)   │   (large)     (large)       │
│                    │                             │
├────────────────────┴─────────────────────────────┤
│  BAT 1: Name .............. score*   balls       │  row 91-115
│  BAT 2: Name .............. score    balls       │
├──────────────────────────────────────────────────┤
│  EXTRAS  w: nb: b: lb:    │  LAST WKT  score    │  row 116-145
├──────────────────────────────────────────────────┤
│  BOWLER: Name   O-M-R-W   │  RUN RATE  / TARGET │  row 146-170
├──────────────────────────────────────────────────┤
│  LAST INNINGS / STATUS BAR / OVERS REMAINING     │  row 171-191
└──────────────────────────────────────────────────┘
```

---

## Development Plan

### Prerequisites

- [ ] Register club on Play Cricket and obtain API token (email `play.cricket@ecb.co.uk`, sign fair usage agreement)
- [ ] Confirm `site_id` for your club
- [ ] Verify Pi has BlueZ ≥ 5.50 (`bluetoothctl --version`)
- [ ] Obtain or fabricate ESP32 remote enclosure and button layout

---

### Phase 1 — Display Rendering (`Raspscoreboard`)

> Get all 9 panels working and rendering a cricket scoreboard layout.

| # | Task | Status |
|---|------|--------|
| 1.1 | Update matrix config: `rows=64`, `cols=64`, `chain_length=3`, `parallel=3`, `hardware_mapping="adafruit-hat"` | |
| 1.2 | Verify physical panel scan order with a full-canvas test pattern (pixel coordinates in each corner) | |
| 1.3 | Select and load BDF fonts — large digits (16–32 px) for total/wickets, medium (10–13 px) for names, small (6–8 px) for labels | |
| 1.4 | Define `MatchState` struct: team names, total, wickets, overs, batter names/scores/balls, bowler figures, extras breakdown, last wicket, run rate, target, innings status, overs remaining | |
| 1.5 | Implement scoreboard renderer: map `MatchState` fields to display zones per the layout above | |
| 1.6 | Add Unix socket listener (`/tmp/scoreboard.sock`) — accept JSON-encoded `MatchState`, update display on each message | |
| 1.7 | Implement secondary screens (fall-of-wickets table, partnership details) with timed rotation or on-demand switching | |
| 1.8 | Add idle/splash screen for when no match is active | |

**Deliverable:** Raspscoreboard accepts `MatchState` JSON on a socket and renders a complete cricket scoreboard across all 9 panels.

---

### Phase 2 — PCS Bluetooth Receiver (`PlayCricketBridge`)

> Receive live scoring from the PCS tablet app over Bluetooth — this is the
> primary integration path and what "Build your own scoreboard" refers to.

| # | Task | Status |
|---|------|--------|
| 2.1 | Study the "Build your own scoreboard" Raspberry Pi Bluetooth receiver code and protocol | |
| 2.2 | Implement Bluetooth Classic (RFCOMM/SPP) listener in Python using `pybluez` or BlueZ D-Bus API — the PCS app advertises as `BespokeScore###` | |
| 2.3 | Parse incoming PCS data packets into `MatchState` fields (total, wickets, overs, batter scores/numbers, extras, last batter, last wicket, last innings, runs required, overs remaining, DLS target/par) | |
| 2.4 | Note PCS app limitations: no partnership, no run rate/target, no batter indicator. Compute run rate locally from total/overs | |
| 2.5 | Handle PCS app quirks: data sent only on change (not continuous); batter position swap on dismissal; 2-second gap between display section updates | |
| 2.6 | Forward `MatchState` to Raspscoreboard via Unix socket on each update | |
| 2.7 | Add "Refresh Scoreboard" command (manual re-request) for when Bluetooth packets are lost | |
| 2.8 | Write `settings.yaml` config: Bluetooth device name filter, socket path, panel geometry | |

**Deliverable:** PCS app on tablet → Bluetooth → PlayCricketBridge → Unix socket → Raspscoreboard renders live score.

---

### Phase 3 — Play Cricket Web API (optional, `PlayCricketBridge`)

> Poll the HTTP API for match summaries — useful as a fallback, for
> pre-match fixture display, or when the PCS app is not being used.

| # | Task | Status |
|---|------|--------|
| 3.1 | Implement `playcricket.py` API client: `result_summary.json` and `match_detail.json` endpoints, authenticated with `api_token` query param | |
| 3.2 | Cache `result_summary` responses; only call `match_detail` when `last_updated` changes (per ECB recommended pattern) | |
| 3.3 | Map API JSON response to `MatchState` — note this data is less granular than PCS (no ball-by-ball, may lag by minutes) | |
| 3.4 | Add mode selector in config: `pcs_bluetooth`, `api_poll`, or `auto` (prefer PCS when connected, fall back to API) | |

**Deliverable:** PlayCricketBridge can display match state from the web API when PCS Bluetooth is unavailable.

---

### Phase 4 — BLE Wireless Remote (`CricketRemote` + `PlayCricketBridge`)

> Manual scoring from a physical handset — independent of Play Cricket
> entirely. For friendlies, practice matches, or when no tablet is available.

| # | Task | Status |
|---|------|--------|
| 4.1 | Define button map: 0, 1, 2, 3, 4, 5, 6, wide, no-ball, bye, leg-bye, wicket, end over, new batter, undo, swap batters | |
| 4.2 | Define BLE command packet format (compact binary: 1-byte command ID + optional payload) | |
| 4.3 | Implement ESP32-S3 firmware: GPIO button matrix with debounce, NimBLE GATT client, transmit command on press | |
| 4.4 | Implement BLE GATT server in PlayCricketBridge using `bleak` (async Python) — receive command packets from ESP32 | |
| 4.5 | Build scoring state machine in PlayCricketBridge: maintain full `MatchState` from button inputs (runs, extras, wickets, overs, strike rotation) | |
| 4.6 | Implement undo: circular buffer of last N state snapshots | |
| 4.7 | Add mode: `remote_manual` — PlayCricketBridge drives `MatchState` from button presses instead of PCS/API | |
| 4.8 | ESP32 power management: deep sleep between presses, wake on GPIO interrupt | |
| 4.9 | LED/buzzer feedback on ESP32: confirm button press received by Pi | |

**Deliverable:** Physical remote → BLE → PlayCricketBridge → Unix socket → Raspscoreboard shows live score with no tablet required.

---

### Phase 5 — Integration, Hardening & Polish

| # | Task | Status |
|---|------|--------|
| 5.1 | End-to-end test: PCS app → Bluetooth → display | |
| 5.2 | End-to-end test: ESP32 remote → BLE → display | |
| 5.3 | End-to-end test: Web API poll → display | |
| 5.4 | Seamless mode switching: if PCS Bluetooth connects mid-match, override API/remote input | |
| 5.5 | Systemd service units for PlayCricketBridge and Raspscoreboard — auto-start on boot | |
| 5.6 | Brightness scheduling: full brightness daytime, dim at dusk (configurable times or light sensor) | |
| 5.7 | Error display states: "No connection", "Waiting for PCS app", "BLE remote disconnected" | |
| 5.8 | Logging and diagnostics: write match log to file for post-match review | |
| 5.9 | Weatherproof enclosure design for outdoor use | |

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IPC: bridge → display | Unix socket, newline-delimited JSON | Simple, debuggable, language-agnostic. Can `socat` into it for testing |
| PCS app comms | Bluetooth Classic (RFCOMM) | PCS app uses SPP-like Bluetooth, not BLE. This is how the "Build your own scoreboard" project works |
| ESP32 remote comms | BLE GATT (via BTLE Mini board on Pi) | Low power, good range for a handset. Separate radio from PCS Bluetooth Classic |
| PlayCricketBridge language | Python 3.9+ | Fast iteration, good Bluetooth/BLE library support (`pybluez`, `bleak`), matches "Build your own scoreboard" community |
| Display rendering | C++ with hzeller/rpi-rgb-led-matrix | Performance-critical path; the hzeller library is the de facto standard |
| ESP32 framework | Arduino via PlatformIO | Largest library ecosystem (NimBLE), familiar tooling |

## Known Constraints & Quirks

- **PCS app sends data only on change** — if a Bluetooth packet is lost, the display stays stale until the next scoring event. Implement a periodic "request refresh" mechanism.
- **2-second gap** between display section updates from PCS app — hardcoded in the app by ECB. Plan renderer to handle partial updates gracefully.
- **Batter swap on dismissal** — PCS moves the remaining batter to "left" position and new batter to "right". The bridge must track this.
- **PCS does not send** partnership, run rate, or target — compute run rate locally; target must be entered manually or via the web API.
- **Bluetooth Classic and BLE are separate radios on the Pi** — PCS uses Classic, ESP32 remote uses BLE via the BTLE Mini board. Both can operate simultaneously.
- **Pi 3B GPIO limit** — maximum 3 parallel HUB75 chains. The 3×3 panel layout (3 parallel × 3 chain) uses all available capacity.
- **Cannot run PCS and PCS Pro simultaneously** to the same scoreboard interface.
- **Pi must run as root** (or with realtime scheduling) for the hzeller LED matrix library.

## Configuration

All runtime configuration lives in `PlayCricketBridge/config/settings.yaml`:

```yaml
mode: auto                    # pcs_bluetooth | api_poll | remote_manual | auto

playcricket:
  api_key: ""
  site_id: ""
  match_id: ""
  poll_interval_s: 30

bluetooth:
  device_filter: "BespokeScore"   # PCS app device name prefix

ble:
  service_uuid: "12345678-..."
  device_name: "CricketRemote"

display:
  ipc_socket: "/tmp/scoreboard.sock"
  panel_rows: 64
  panel_cols: 64
  chain_length: 3
  parallel: 3
  brightness: 75
  brightness_schedule:
    - { time: "06:00", brightness: 75 }
    - { time: "20:00", brightness: 40 }
```
