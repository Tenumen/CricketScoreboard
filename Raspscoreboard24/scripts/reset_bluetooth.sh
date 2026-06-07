#!/bin/bash
# reset_bluetooth.sh -- triggered by the admin-console "Reset Bluetooth" button.
#
# Recovery for a wedged BLE link: the phone can't connect / no tokens arrive and
# the bridge's own re-advertise watchdog (commit 9a04eaa) hasn't recovered it.
# Resets the Bluetooth stack from the bottom up, then restarts the bridge so it
# re-registers its GATT service, re-advertises and re-runs adapter hygiene
# (Powered / Pairable / Discoverable / DiscoverableTimeout=0).
#
# Deliberately does NOT touch scoreboard24.service -- the LED wall keeps running.
# The bridge restart clears accumulated match state, but the phone re-sends its
# init tokens on reconnect so a live match rebuilds. Spawned detached by
# debug_server.cpp; runs as root (scoreboard24.service User=root), so plain
# systemctl works without sudo.

set -u

logger -t scoreboard24-btreset "admin-console Bluetooth reset triggered"

# 1. Reset BlueZ and the controller. Clears a wedged adapter that the bridge's
#    in-process watchdog can't recover on its own.
if ! /bin/systemctl restart bluetooth.service; then
    logger -t scoreboard24-btreset "bluetooth.service restart returned non-zero; continuing"
fi

# 2. Give BlueZ time to re-initialise the adapter before the bridge re-registers
#    its GATT app and advertisement against it.
sleep 3

# 3. Restart the bridge: re-runs run_peripheral() -> adapter hygiene, GATT
#    registration, advertising and the re-advertise watchdog.
if ! /bin/systemctl restart playcricket-ble-bridge.service; then
    logger -t scoreboard24-btreset "playcricket-ble-bridge.service restart returned non-zero"
fi

logger -t scoreboard24-btreset "Bluetooth reset complete"
