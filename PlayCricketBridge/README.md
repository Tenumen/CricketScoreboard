# PlayCricketBridge

Raspberry Pi service that bridges all scoring inputs to the HUB75 display.

## Three input modes

| Mode | Source | Protocol |
|------|--------|----------|
| `pcs_bluetooth` | PCS scorer app (Android/iOS) | Bluetooth Classic (RFCOMM) |
| `api_poll` | Play Cricket web API v2 | HTTPS JSON |
| `remote_manual` | ESP32 physical remote | BLE GATT (via BTLE Mini board) |
| `auto` | Prefer PCS when connected, fall back to API or remote | — |

## Responsibilities

1. **PCS Bluetooth receiver** — listen for Bluetooth Classic connections from
   the PCS app (device name `BespokeScore###`), parse ball-by-ball data.
2. **Play Cricket API client** — poll `result_summary` and `match_detail`
   endpoints for match state when PCS is unavailable.
3. **BLE GATT server** — receive button-press commands from the CricketRemote
   ESP32 and maintain scoring state locally.
4. **Display IPC** — publish normalised `MatchState` JSON to Raspscoreboard
   via a Unix socket (`/tmp/scoreboard.sock`).

## Project structure

```
PlayCricketBridge/
├── src/
│   ├── pcs_receiver.py   # PCS Bluetooth Classic listener
│   ├── playcricket.py     # Play Cricket web API client
│   ├── ble_server.py      # BLE GATT server (ESP32 remote commands)
│   ├── score_engine.py    # Scoring state machine (for remote_manual mode)
│   └── bridge.py          # Main service — mode switching, IPC output
├── tests/
├── config/
│   └── settings.yaml
└── README.md
```

## Requirements

- Python 3.9+
- BlueZ >= 5.50 (`bluetoothctl --version`)
- `pybluez` or BlueZ D-Bus API (for Bluetooth Classic / PCS)
- `bleak` (for BLE / ESP32 remote)
- `requests` (for Play Cricket HTTP API)
- `pyyaml` (config)

## Running

```bash
pip install -r requirements.txt
python src/bridge.py --config config/settings.yaml
```
