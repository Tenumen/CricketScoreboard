#!/bin/bash
# shutdown_pi.sh -- triggered by the admin-console "Shut down Pi" button.
#
# Stops scoreboard24.service synchronously first so its ExecStopPost mailer
# gets the full TimeoutStopSec budget with networking still up. Then powers
# the Pi off. Spawned detached by debug_server.cpp; KillMode=process on the
# unit keeps this script alive after it stops its own parent.

set -u

logger -t scoreboard24-shutdown "admin-console shutdown triggered"

if ! /bin/systemctl stop scoreboard24.service; then
    logger -t scoreboard24-shutdown "stop returned non-zero; continuing to poweroff"
fi

logger -t scoreboard24-shutdown "issuing poweroff"
exec /bin/systemctl poweroff
