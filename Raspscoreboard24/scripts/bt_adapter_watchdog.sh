#!/bin/bash
# bt_adapter_watchdog.sh -- boot-time recovery for the USB Realtek RTL8761B
# Bluetooth dongle.
#
# That dongle intermittently fails its firmware download on boot:
#   hci0: command 0xfc20 tx timeout
#   hci0: RTL: download fw command failed (-110)
# which leaves hci0 with a null BD address (00:00:00:00:00:00) and DOWN -- no
# Bluetooth at all (the onboard radio is disabled). A warm reboot can't fix it.
#
# This runs ONCE at boot (oneshot), ordered After=bluetooth.service and
# Before=playcricket-ble-bridge.service, so the bridge only starts once a healthy
# adapter is confirmed. On a normal boot the adapter is already healthy and this
# exits in ~1s. On a failed boot it re-triggers the firmware download by
# re-enumerating the USB device (the only thing software can do -- it cannot
# power-cycle a Pi 3B USB port, so a truly wedged chip still needs a physical
# re-plug, which it logs).
#
# Runs as root (unit has no User=). Logs to the journal via logger.

set -u

LOGTAG="scoreboard24-btwatchdog"
log() { logger -t "$LOGTAG" "$*"; }

# Healthy = hci0 exists with a real (non-zero) BD address, i.e. firmware loaded.
adapter_healthy() {
    local addr
    addr=$(hciconfig hci0 2>/dev/null | sed -n 's/.*BD Address: \([0-9A-Fa-f:]\{17\}\).*/\1/p')
    [ -n "$addr" ] && [ "$addr" != "00:00:00:00:00:00" ]
}

# Find the dongle's USB sysfs id (e.g. "1-1.3"). Its product string is set at
# USB enumeration and is present even when the firmware download failed.
find_bt_usb() {
    local p
    for p in /sys/bus/usb/devices/*/product; do
        [ -e "$p" ] || continue
        if grep -qx "Bluetooth Radio" "$p" 2>/dev/null; then
            basename "$(dirname "$p")"
            return 0
        fi
    done
    return 1
}

reenumerate_usb() {
    local dev="$1"
    echo "$dev" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || return 1
    sleep 3
    echo "$dev" > /sys/bus/usb/drivers/usb/bind   2>/dev/null || return 1
    return 0
}

# 1. Grace period: a healthy boot is already good here, so this exits at once.
#    A slow-but-successful firmware load gets up to ~25s before we intervene.
for i in $(seq 1 25); do
    if adapter_healthy; then
        log "adapter healthy at boot (after ${i}s); nothing to do"
        exit 0
    fi
    sleep 1
done

log "adapter unhealthy after grace period (null BD address / DOWN); attempting recovery"

# 2. Up to 3 recovery attempts: re-enumerate the USB device to re-trigger the
#    firmware download; fall back to reloading the btusb driver.
for attempt in 1 2 3; do
    dev=$(find_bt_usb || true)
    if [ -n "${dev:-}" ]; then
        log "attempt ${attempt}: re-enumerating USB device ${dev}"
        reenumerate_usb "$dev" || log "attempt ${attempt}: unbind/rebind returned non-zero"
    else
        log "attempt ${attempt}: BT USB device not found; reloading btusb"
        modprobe -r btusb 2>/dev/null; sleep 1; modprobe btusb 2>/dev/null
    fi

    # Wait for the firmware download to settle.
    for i in $(seq 1 10); do
        if adapter_healthy; then
            log "adapter recovered on attempt ${attempt}; restarting bluetooth.service"
            systemctl restart bluetooth.service 2>/dev/null || true
            sleep 2
            adapter_healthy && log "recovery complete; adapter healthy" \
                            || log "warning: adapter check after bluetooth restart failed"
            exit 0
        fi
        sleep 1
    done
done

log "ERROR: BT adapter could not be recovered in software -- physically unplug and re-plug the USB Bluetooth dongle (or do a full power-off) to clear the firmware-load failure"
exit 0
