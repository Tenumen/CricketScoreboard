#!/bin/bash
# reboot_pi.sh -- triggered by the admin-console "Reboot Pi" button.
#
# Stops scoreboard24.service synchronously first so its ExecStopPost mailer
# gets the full TimeoutStopSec budget with networking still up. Then reboots
# the Pi. Spawned detached by debug_server.cpp; KillMode=process on the unit
# keeps this script alive after it stops its own parent.

set -u

logger -t scoreboard24-reboot "admin-console reboot triggered"

if ! /bin/systemctl stop scoreboard24.service; then
    logger -t scoreboard24-reboot "stop returned non-zero; continuing to reboot"
fi

logger -t scoreboard24-reboot "issuing reboot"
exec /bin/systemctl reboot
