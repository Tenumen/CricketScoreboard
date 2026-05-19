# Raspscoreboard24

Driver for the 24-panel (6 wide × 4 deep) HUB75 cricket scoreboard at Aston on Trent VCC.

Forked from `../Raspscoreboard/` (which is now deprecated — kept for reference and the
older 3-panel test rig).

## Hardware

- Raspberry Pi 3B + Electrodragon Active RGB-LED-Matrix HAT
- 24 × 64×64 P3 outdoor HUB75E panels, drivers ICN2037DP, 1/16 scan, ~1920 Hz refresh
- 3 parallel chains of 8 panels each (see [`DISPLAY_NOTES_24.md`](DISPLAY_NOTES_24.md))

## Build

```bash
cd Raspscoreboard24
make
```

The shared `lib/rpi-rgb-led-matrix` is a symlink to the legacy fork's submodule, so the
hzeller static library only needs building once.

## Run

```bash
# Calibration — one panel lit at a time, 1.5s each
sudo ./scoreboard24 --calibrate

# Calibration — all 24 panels labelled simultaneously
sudo ./scoreboard24 --calibrate=all

# Normal — render LAST INNINGS test pattern on the wall
sudo ./scoreboard24
```

`--calibrate` must be the literal string `--calibrate` or `--calibrate=all`; all other
flags fall through to hzeller's `ParseOptionsFromFlags` (so `--led-slowdown-gpio=4`,
`--led-pwm-bits=9`, etc. still work for ad-hoc tuning).

## Editing the panel wiring

`src/panel_layout.h` is the single source of truth for the chain ordering and per-panel
rotation. Edit it and rebuild when calibration shows something wrong. See
`DISPLAY_NOTES_24.md` for the workflow.

## What's implemented

- 384 × 256 logical canvas via `GridCanvas` (translates logical → hardware pixels)
- Calibration mode (two passes)
- Row 4 LAST INNINGS, recentred for the new canvas

Rows 1–3 are spec-only — pixel coords are sketched in `DISPLAY_NOTES_24.md` and need
implementing.

## Match-data sources

The binary polls a Play-Cricket-shaped HTTP API set by `api_base_url` in
`config.json`. Three setups are supported, without any rebuild:

| Setup           | `api_base_url`                       | Notes                                                           |
| --------------- | ------------------------------------ | --------------------------------------------------------------- |
| Live (internet) | empty (default play-cricket.com)     | The real ECB API. Needs club `api_token` + `club_site_id`.      |
| Mock dev server | `http://192.168.1.150:5050`          | The sibling `mock_playcricket/` Flask app — for off-ground dev. |
| Bluetooth bridge | `http://127.0.0.1:5051`             | The sibling `../playcricket_ble_bridge/` Python service — receives scores over BLE from the Play-Cricket Scorer Android app on the Pixel 9a. Use this on match day when there is no internet. |

See each sibling's README for setup details.
