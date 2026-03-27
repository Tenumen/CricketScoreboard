# Display Layout Notes

## Panel Configuration

- 3 panels daisy-chained: 192×64 canvas
- Left panel: x 0–63
- Middle panel: x 64–127
- Right panel: x 128–191

## Idle / Splash Screen Layout

### Middle Panel — Club Logo
- Source: `photo.jpg` (Aston on Trent VCC crest)
- Resized to 64×64 with white background replaced with black (`-fuzz 20% -transparent white`)
- Positioned at x=64, y=0

### Left Panel — Home Team Name
- Text: ASTON / ON / TRENT (3 lines)
- Font: Helvetica-Bold, pointsize 12
- Colour: white
- Positions (NorthWest gravity):
  - "ASTON" — x=10, y=10
  - "ON" — x=19, y=24
  - "TRENT" — x=10, y=38

### Right Panel — Away Team Name
- Text: MELBOURNE (1 line)
- Font: Helvetica-Bold, pointsize 10
- Colour: white
- Position (NorthWest gravity):
  - "MELBOURNE" — x=129, y=18

## ImageMagick Command

```bash
convert -size 192x64 xc:black \
  logo_64.png -geometry +64+0 -composite \
  -fill white -font Helvetica-Bold \
  -pointsize 12 -gravity NorthWest \
  -annotate +10+10 'ASTON' \
  -annotate +19+24 'ON' \
  -annotate +10+38 'TRENT' \
  -pointsize 10 \
  -annotate +129+18 'MELBOURNE' \
  display_full.png
```

## Display Command

```bash
sudo led-image-viewer \
  --led-rows=64 --led-cols=64 --led-chain=3 \
  --led-pwm-bits=7 --led-slowdown-gpio=4 \
  -w3600 display_full.png
```

---

## Row 2 — Scores (OVERS / RUNS / WKTS)

Rendered in C++ (`src/main.cpp`) using BDF fonts.

### Labels (top of panel, tops aligned at y≈1)

| Label | Font | Width | Colour | x | y (baseline) |
|-------|------|-------|--------|---|--------------|
| OVERS | 7x13B.bdf | 5×7 = 35px | white | 4 | 12 |
| RUNS | 10x20.bdf | 4×10 = 40px | white | 76 | 17 |
| WKTS | 7x13B.bdf | 4×7 = 28px | white | 157 | 12 |

### Numbers (below labels)

| Value | Font | Digit width | Colour | x | y (baseline) |
|-------|------|-------------|--------|---|--------------|
| Overs (2-digit) | texgyre-27.bdf | ~15px/digit | green | 6 | 46 |
| Runs (3-digit) | dejavu-mono-bold-46.bdf | ~28px/digit (84px total) | yellow | 54 | 58 |
| Wkts (1-2 digit) | texgyre-27.bdf | ~15px/digit | orange | auto-centred at x=171 | 46 |

### Notes

- RUNS number uses a custom BDF font generated from DejaVu Sans Mono Bold at 46pt via `otf2bdf`
  - File: `fonts/dejavu-mono-bold-46.bdf` (on Pi only, not in git)
  - Generated with: `otf2bdf -p 46 -r 72 /usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf -o fonts/dejavu-mono-bold-46.bdf`
- RUNS number can spread a few pixels into the left and right panels
- WKTS number auto-centres based on digit count (no leading zero for single digits)
- OVERS label positioned at 1/3 of left panel, WKTS at 2/3 of right panel
