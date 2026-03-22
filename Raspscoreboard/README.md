# Raspscoreboard

HUB75 LED panel scoreboard running on a Raspberry Pi 3B, using the
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library.

## Hardware

| Component | Notes |
|-----------|-------|
| Raspberry Pi 3B | Must run as root or with realtime scheduling |
| HUB75 / HUB75E panel | 32×64 px default; chain/parallel configurable |
| 5 V / 4 A power supply | Per panel — never power panels from the Pi's GPIO 5 V |
| Ribbon cable | Standard 16- or 32-pin IDC |

### Wiring

See [`lib/rpi-rgb-led-matrix/wiring.md`](lib/rpi-rgb-led-matrix/wiring.md) for the full
pinout.  The default `hardware_mapping = "regular"` maps to the original hzeller wiring.
If you use an Adafruit RGB Matrix HAT, change it to `"adafruit-hat"` or `"adafruit-hat-pwm"`.

## Building

```bash
# Clone with submodules (first time)
git submodule update --init --recursive

# Compile
make
```

## Running

```bash
# Must be root for GPIO / DMA access
sudo ./scoreboard

# Override panel settings at runtime
sudo ./scoreboard --led-rows=64 --led-cols=64 --led-chain=2 --led-parallel=1 \
                  --led-brightness=75 --led-gpio-slowdown=2
```

Pass `--help` to see all available flags from the library.

## Project structure

```
Raspscoreboard/
├── src/
│   └── main.cpp          # Entry point — scoreboard render loop
├── include/              # Your own headers go here
├── lib/
│   └── rpi-rgb-led-matrix/   # hzeller library (git submodule)
├── Makefile
└── README.md
```

## Configuration (src/main.cpp)

| Variable | Default | Description |
|----------|---------|-------------|
| `rows` | 32 | Panel pixel height |
| `cols` | 64 | Panel pixel width |
| `chain_length` | 1 | Panels daisy-chained end-to-end |
| `parallel` | 1 | Independent parallel chains (max 3 on Pi 3) |
| `brightness` | 50 | Brightness 1–100 % |
| `gpio_slowdown` | 2 | Reduce GPIO speed to fix glitches (1–4) |

## Adding scoreboard logic

Edit `src/main.cpp` inside the `while (!interrupt_received)` loop.  Key API calls:

```cpp
canvas->Fill(r, g, b);                          // Fill entire canvas
canvas->SetPixel(x, y, r, g, b);               // Single pixel
DrawText(canvas, font, x, y, color, bg, text);  // BDF font text
DrawCircle(canvas, cx, cy, r, color);           // Circle outline
DrawLine(canvas, x0, y0, x1, y1, color);        // Line
canvas = matrix->SwapOnVSync(canvas);           // Push frame (vsync)
```

Full API: [`lib/rpi-rgb-led-matrix/include/led-matrix.h`](lib/rpi-rgb-led-matrix/include/led-matrix.h)
and [`graphics.h`](lib/rpi-rgb-led-matrix/include/graphics.h).
