# CricketRemote

ESP32-S3 firmware for the wireless cricket scoreboard remote control.

## Hardware

| Component | Notes |
|-----------|-------|
| Adafruit ESP32-S3 Feather | 4 MB flash, 2 MB PSRAM |
| BTLE Mini board | Handles BLE communication to the Raspberry Pi |
| Physical buttons | Mapped to scoring actions (runs, wickets, extras, etc.) |

## Communication

Communicates with `PlayCricketBridge` (running on the Pi) over BLE.
Each button press sends a compact JSON or binary command packet.

## Development

Developed with PlatformIO (recommended) or Arduino IDE.

Target board: `adafruit_feather_esp32s3`

## Project structure

```
CricketRemote/
├── src/
│   └── main.cpp        # Firmware entry point
├── include/            # Headers
├── lib/                # Third-party libraries
├── platformio.ini      # PlatformIO build config
└── README.md
```
