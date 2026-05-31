#!/usr/bin/env bash
# update.sh — pull latest commit, rebuild, restart the scoreboard service.
# Snapshots the previous binary + commit hash so rollback.sh can revert.
#
# Spawned (detached) by the admin-console "Update from git" button.
# Also runnable directly: `sudo bash scripts/update.sh`.

set -euo pipefail

# The scoreboard24 service runs as root (HUB75 needs GPIO), so this script —
# spawned by the admin console — runs as root too, while the git repo is owned
# by 'tenumen'. Git's safe.directory protection otherwise aborts every command
# with "detected dubious ownership", before the snapshot/pull/build/restart.
# Trust all repos for this script's git calls AND the Makefile's `git rev-parse`
# (make inherits the environment).
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0='*'

REPO_DIR="${REPO_DIR:-/home/tenumen/scoreboard24}"
STATE_DIR="/var/lib/scoreboard24"
LOG="$STATE_DIR/last_update.log"

mkdir -p "$STATE_DIR"

# Stream everything below into the log (also for stdout/stderr) so the user
# can `cat /var/lib/scoreboard24/last_update.log` to see what happened.
{
    echo
    echo "=== update started $(date -Iseconds) ==="
    cd "$REPO_DIR"

    # 1. Snapshot rollback target BEFORE we mutate anything.
    git rev-parse HEAD > "$STATE_DIR/prev_commit"
    if [[ -f scoreboard24 ]]; then
        cp scoreboard24 "$STATE_DIR/scoreboard24.prev"
    fi
    echo "snapshot:   $(cat "$STATE_DIR/prev_commit")"

    # 2. Pull. --ff-only refuses to merge surprise commits made on the Pi.
    echo "fetch + pull..."
    git fetch --quiet origin
    git pull --ff-only --quiet
    NEW_HEAD=$(git rev-parse HEAD)
    echo "new head:   $NEW_HEAD"

    # 3. Build. Ensure debug_server.cpp recompiles so BUILD_GIT_HASH is fresh.
    #    If make fails the OLD binary is still in place — we just exit and
    #    the running service is unaffected.
    touch src/debug_server.cpp
    echo "make..."
    make -j2

    # 4. Restart via systemd. KillMode=process means this script (a separate
    #    process tree from scoreboard24) keeps running through the restart.
    echo "=== restarting $(date -Iseconds) ==="
    systemctl restart scoreboard24.service

    echo "=== update done $(date -Iseconds) ==="
} >> "$LOG" 2>&1
