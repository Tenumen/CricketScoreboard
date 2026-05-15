# Display Layout Notes — 24-panel grid

## Panel Configuration

- 24 P3 outdoor HUB75E panels, 64×64 each, arranged in a 6 wide × 4 deep grid.
- Logical canvas: **384 × 256** (front view, origin top-left).
- Grid label convention: columns 1–6, rows A–D.
  - Row A is the top of the display; row D the bottom.
  - **Column 1 is on the LEFT edge** of the display (audience view); column 6 on the right edge.
  - The chain enters from the audience-left side, so columns count up left→right.
- Drivers: ICN2037DP (or similar), 1/16 scan, refresh ≈1920 Hz, 120 fps.

```
              x=0..63  64..127  128..191  192..255  256..319  320..383
              col1     col2     col3      col4      col5      col6
y=  0..63 A:  A1       A2       A3        A4        A5        A6     <- top
y= 64..127 B: B1       B2       B3        B4        B5        B6
y=128..191 C: C1       C2       C3        C4        C5        C6
y=192..255 D: D1       D2       D3        D4        D5        D6     <- bottom
```

## Hardware Chains

The Pi 3B + Electrodragon HAT drives the panels via 3 parallel chains, 8 panels each
(chain order = the order panels are visited starting at the HAT output, position 0 → 7):

| HAT silk-screen output | Library `parallel` index (see `panel_layout.h`) | Chain order |
|---|---|---|
| BOTTOM | `kParBottom` (default 0) | B1, A1, A2, A3, A4, A5, A6, B6 |
| MIDDLE | `kParMiddle` (default 1) | B2, C2, C3, B3, B4, C4, C5, B5 |
| TOP    | `kParTop`    (default 2) | C1, D1, D2, D3, D4, D5, D6, C6 |

The mapping from logical (x, y) → hardware (parallel, chain_pos, panel-local x/y, rotation)
is done in software by `GridCanvas::SetPixel`, which reads `kPanelLayout` in
`src/panel_layout.h`. **Edit that file** to swap parallel indices, fix a panel position, or
flip a panel's rotation 0 ↔ 180 if calibration shows it's upside-down.

## Calibration Workflow

```bash
cd Raspscoreboard24
make
sudo ./scoreboard24 --calibrate         # one panel at a time, 1.5s each
sudo ./scoreboard24 --calibrate=all     # every panel labelled at once
```

For each panel the calibration draws:
- A per-row coloured background (A=red, B=green, C=blue, D=amber)
- The label ("A1", "B4", …) centred in white
- A small L-bracket in the **top-left corner** of the logical 64×64 region

Workflow when a panel reads wrong:
- **Wrong panel lit / wrong row colour** → swap the `kParBottom/kParMiddle/kParTop`
  constants in `panel_layout.h`, or fix that panel's `chain_pos` entry.
- **Right panel, label is upside-down** → flip that panel's `rotation` between 0 and 180.
- **Garbled / colour-bands on every panel** → uncomment `panel_type = "FM6126A"` in
  `main.cpp`. Try `led_rgb_sequence = "RGB"`/`"BGR"`/etc. if colours are wrong but stable.
- **Flicker or tearing** → bump `gpio_slowdown` from 2 → 3 → 4.

Rebuild (`make`) and re-run after each edit.

## Tuning Knobs (`src/main.cpp`)

| Option | Current | Notes |
|---|---|---|
| `hardware_mapping` | `"regular"` | Electrodragon HAT |
| `rows` × `cols` | 64 × 64 | per panel |
| `chain_length` | 8 | from `panel_layout.h` |
| `parallel` | 3 | from `panel_layout.h` |
| `pwm_bits` | 11 | full quality; lower to 7–9 if flicker is severe |
| `brightness` | 50% | outdoor panels may want higher |
| `gpio_slowdown` | 2 | start low; raise if pixels are noisy |
| `panel_type` | (default) | set to `"FM6126A"` if ICN2037 needs that init |

## Scoreboard Layout on the 384 × 256 Canvas

The display is organised as a **3-column × 4-row grid** of "cells", each cell being
128 px wide × 64 px tall (i.e. 2 panels × 1 panel). Cell boundaries are guides, not
hard limits — text may extend beyond a cell if a value is wide (e.g. long team name).

```
              Left (x=0..127)        Middle (x=128..255)        Right (x=256..383)
Row A (0..63)   Club crest              ASTON ON TRENT             TO WIN <target>
                                        vs                         (hidden unless chasing)
                                        MELBOURNE
Row B (64..127) "RUNS" label            <runs> (big)               "WKTS" <wkts>
Row C (128..191)"BAT 1" / <name> *      <bat1 score> (big)         "OVERS" <overs>
Row D (192..255)"BAT 2" / <name>        <bat2 score> (big)         "LAST INNINGS" <runs> <wkts>
```

### Colour Spec

| Element | Colour |
|---|---|
| Home team name (ASTON ON TRENT) | cyan / light blue |
| "vs" | white |
| Opponent name (MELBOURNE) | green |
| Target / RUNS / LAST INNINGS numbers (yellow team score) | amber/orange |
| Wickets number | red/coral (warning) |
| Overs number | green |
| Big current-batter scores | white |
| Batter names | cyan |
| Strike marker (*) | cyan |
| All labels (RUNS, WKTS, OVERS, BAT 1, BAT 2, LAST INNINGS, TO WIN) | white |

### Behavioural rules

- **TO WIN** cell shows the target *only when chasing* (i.e. batting second). Hidden otherwise.
- **BAT 1 / BAT 2** show the two current batters. Asterisk after the name marks who is on strike.
- **LAST INNINGS** shows the previous innings' score; when not applicable (first innings of a one-innings match) this cell is empty.

### Fonts in use

- Labels (`RUNS`, `WKTS`, `OVERS`, `BAT 1`, etc.): `7x13B.bdf` from the library bundle.
- Team names + batter names: `7x13B.bdf` for now (may upgrade to a sharper bitmap font later).
- Big numbers: `dejavu-mono-bold-42.bdf` (generated on the Pi — see Fonts section below).
- Smaller secondary numbers (TO WIN target, LAST INNINGS pair): same `dejavu-mono-bold-42.bdf` or its 46 px sibling — pick what fits each cell.

### Implementation status

| Cell | Status |
|---|---|
| All 12 cells (text content) | NOT YET — pending rewrite of `main.cpp` from scratch |
| Logo bitmap loading | NOT YET — placeholder rectangle will be drawn until PNG loader is added |

The legacy Row D (LAST INNINGS centred at y≈240) is being replaced by the new 3-column layout; the previously-implemented version no longer matches the spec.

## Fonts

- Bundled (in `lib/rpi-rgb-led-matrix/fonts/`): `7x13B.bdf`, `10x20.bdf`, etc.
- Generated on the Pi (not in git):
  - `fonts/dejavu-mono-bold-42.bdf`
  - `fonts/dejavu-mono-bold-46.bdf`
  - Build via `otf2bdf -p 42 -r 72 /usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf -o fonts/dejavu-mono-bold-42.bdf`
