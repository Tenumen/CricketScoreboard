#!/bin/bash
# forget_bluetooth.sh -- triggered by the admin-console "Forget paired devices"
# button.
#
# Clears every Bluetooth bond the Pi holds. Use when a phone/tablet reports it's
# connected but no score appears, or it can see 'scoreboard24' but won't connect
# -- symptoms of a stale pairing whose link keys have desynced (after a bridge
# restart, a forced disconnect, or an odd boot).
#
# Removing a bond on the Pi disconnects that device -- intended; you get a clean
# slate. The caller MUST ALSO "Forget" the scoreboard in the phone/tablet's
# Bluetooth settings and pair again: clearing only one side just re-creates the
# mismatch.
#
# Deliberately does NOT restart the bridge or the wall -- removing bonds doesn't
# need it, and a bridge restart would wipe in-progress match state. The adapter
# keeps advertising throughout. Spawned detached by debug_server.cpp; runs as
# root (scoreboard24.service User=root), so bluetoothctl can manage bonds.

set -u

logger -t scoreboard24-btforget "admin-console 'forget paired devices' triggered"

removed=0
# `bluetoothctl devices` lists every known device, one per line:
#   "Device AA:BB:CC:DD:EE:FF Name Here"
for mac in $(bluetoothctl devices 2>/dev/null | awk '/^Device /{print $2}'); do
    if bluetoothctl remove "$mac" >/dev/null 2>&1; then
        logger -t scoreboard24-btforget "removed bond $mac"
        removed=$((removed + 1))
    else
        logger -t scoreboard24-btforget "failed to remove $mac"
    fi
done

logger -t scoreboard24-btforget "done; $removed bond(s) removed"
