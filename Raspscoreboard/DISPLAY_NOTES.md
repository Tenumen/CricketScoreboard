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
