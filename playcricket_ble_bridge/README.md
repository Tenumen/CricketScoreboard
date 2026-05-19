# playcricket_ble_bridge

A small Python service that receives live cricket scores from the
**Play-Cricket Scorer** Android app's *Generic external scoreboard*
output (Bluetooth LE) and re-exposes them as a Play-Cricket HTTP API on
localhost.

The Pi's existing `scoreboard24` C++ binary polls that localhost HTTP API
exactly as it polls play-cricket.com — no rebuild, no C++ changes. Run
this bridge alongside it and the wall mirrors whatever the phone scores,
fully offline.

```
 ┌────────────────────┐    BLE GATT     ┌─────────────────────────────┐
 │ Pixel 9a           │ ──notifications─▶ │ playcricket_ble_bridge      │
 │ Play-Cricket       │  (token stream)  │   Flask :5051               │
 │ Scorer app         │                  └──────────┬──────────────────┘
 └────────────────────┘                             │ HTTP poll
                                                    ▼
                                         ┌─────────────────────────────┐
                                         │ scoreboard24 (C++)          │
                                         │ HUB75 wall                  │
                                         └─────────────────────────────┘
```

## Quick start

```bash
cd playcricket_ble_bridge
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

./run.sh --our-club-id 12345         # default: 127.0.0.1:5051
```

Then in the Play-Cricket Scorer Android app:

1. Settings → External scoreboard → *Generic*.
2. Scan for devices; pair with `scoreboard24`.
3. Start a match. Ball-by-ball updates stream over BLE to this bridge.

Point the Pi's `~/scoreboard24/config.json` at the bridge:

```jsonc
"mock_mode": false,
"api_base_url": "http://127.0.0.1:5051"
```

`sudo systemctl restart scoreboard24` — done.

## CLI flags

```
python -m playcricket_ble_bridge [options]

  --host HOST                HTTP bind address (default: 127.0.0.1)
  --port PORT                HTTP bind port    (default: 5051)
  --our-club-id ID           Our Play-Cricket site id; affects which side
                             the wall labels as 'home' vs 'opponent'.
  --discovery-log PATH       Append every received BLE token to PATH
                             (default: ./discovery.log)
  --no-ble                   Skip the BLE peripheral; HTTP-only mode for
                             local development.
  -v, --verbose              Debug logging.
```

## Protocol

The "Generic" output is community-documented, not formally specified. Wire
shape: each BLE write is a single ASCII string — three-byte item code +
value. Sources:

- BLE service UUID: `5a0d6a15-b664-4304-8530-3a0ec53e5bc1`
- Notify characteristic: `df531f62-fc0b-40ce-81b2-32a6262ea440`
- buildyourownscoreboard.wordpress.com (overview)
- Andy Smy, *Eco Play-Cricket Bluetooth External Scoreboards* (Medium) —
  full token table.

The bridge's token table lives in `playcricket_ble_bridge/tokens.py`.
Anything received with a code not in that table is logged to
`discovery.log` (counted in the `unknown_codes` map exposed at
`/api/sim/info`) so we can add it later.

## Endpoints

| Path                            | Purpose                                       |
| ------------------------------- | --------------------------------------------- |
| `GET /api/v2/result_summary.json` | Used by scoreboard24 to discover match id   |
| `GET /api/v2/match_detail.json`   | Used by scoreboard24 every poll             |
| `GET /api/sim/info`               | Bridge debug: generation, unknown_codes     |

## Tests

```bash
cd playcricket_ble_bridge
pip install pytest
PYTHONPATH=. pytest -v
```

BLE smoke tests need a real BlueZ stack and a phone — not part of the
unit-test suite.

## Operational notes

- **Pairing is per-device.** The first time the phone connects, accept
  the pairing request; subsequent boots reconnect automatically.
- **One central at a time.** Bless allows a single connected central; if
  two phones try to pair, the second is rejected.
- **Discovery log.** Append-only at `discovery.log`. Truncate it
  yourself before a real fixture if you want a clean capture.
- **No scoring UI here.** The bridge is read-only: only the phone can
  change state. To replay a match offline, use the sibling
  `mock_playcricket/` Flask app instead.
- **Restarting the bridge breaks the active GATT session.** If you
  `systemctl restart playcricket-ble-bridge` while the phone is
  connected, the Play-Cricket Scorer app holds a stale service handle
  and silently writes into the void — Android still shows the device
  as connected, but no tokens reach the bridge. Fix: in the app go to
  External scoreboard settings, **disconnect** from `scoreboard24`,
  then **reconnect**. That forces a fresh GATT service discovery and
  the connection-init sequence (B1N / B2N / FTN / COV / …) re-fires.
  If a tap-disconnect doesn't wake it up: force-stop the app; last
  resort: "Forget" the device in Android BT settings and re-pair.
- **Pi-side first-time enable.** The bridge needs `bluetooth.service`
  active and a pairing agent. On a fresh Pi: ensure
  `/boot/firmware/config.txt` does NOT contain `dtoverlay=disable-bt`
  (Pi 3B's onboard BT is disabled by that overlay), then
  `sudo apt install bluez-tools` and run a NoInputNoOutput agent —
  `Raspscoreboard24/scripts/playcricket-ble-bridge.service` and a
  sibling `bt-agent.service` unit are documented in CHANGE.md.

## Systemd unit

`Raspscoreboard24/scripts/playcricket-ble-bridge.service` installs to
`/etc/systemd/system/`. It assumes the bridge lives at
`/home/tenumen/playcricket_ble_bridge` on the Pi. See
`Raspscoreboard24/scripts/install_pi.sh` for the install step (added
alongside the scoreboard24 unit).
