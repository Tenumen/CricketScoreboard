#!/usr/bin/env bash
# update.sh — pull latest commit, rebuild, restart the scoreboard service.
# Snapshots the previous binary + commit hash so rollback.sh can revert.
#
# Spawned (detached) by the admin-console "Update from git" button.
# Also runnable directly: `sudo bash scripts/update.sh`.

set -Eeuo pipefail

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
STATUS="$STATE_DIR/update_status.json"

mkdir -p "$STATE_DIR"

# Machine-readable progress marker the admin console polls via /api/version, so
# the operator can see the update happening — and, crucially, see a FAILURE
# rather than it failing silently.
status() {  # $1 = state (running|done|failed)   $2 = phase
    printf '{"state":"%s","phase":"%s","ts":%s}\n' "$1" "$2" "$(date +%s)" > "$STATUS"
}

# Guard against concurrent runs. The admin button pressed twice would otherwise
# spawn two parallel `make` jobs; on the 1 GB Pi 3B that exhausts RAM, thrashes
# into swap, and wedges the whole machine (it happened — 2026-06-22). Hold an
# exclusive, non-blocking lock for this script's lifetime; a second invocation
# bails out immediately instead of building in parallel.
exec 9>"$STATE_DIR/update.lock"
if ! flock -n 9; then
    echo "$(date -Iseconds): update already in progress — this invocation exits" >> "$LOG"
    exit 0
fi

# On any unexpected failure (set -e), mark the status FAILED at the phase we
# reached so the console surfaces it. The OLD binary is left running untouched.
PHASE=start
trap 'status failed "$PHASE"' ERR

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
    PHASE=pull; status running pull
    echo "fetch + pull..."
    git fetch --quiet origin
    git pull --ff-only --quiet
    NEW_HEAD=$(git rev-parse HEAD)
    echo "new head:   $NEW_HEAD"

    # 3. Build. Ensure debug_server.cpp recompiles so BUILD_GIT_HASH is fresh.
    #    If make fails the OLD binary is still in place — we just exit and
    #    the running service is unaffected.
    PHASE=build; status running build
    touch src/debug_server.cpp
    echo "make..."
    make -j2

    # 4. Restart via systemd. KillMode=process means this script (a separate
    #    process tree from scoreboard24) keeps running through the restart.
    PHASE=restart; status running restart
    echo "=== restarting $(date -Iseconds) ==="
    systemctl restart scoreboard24.service

    status done ""
    echo "=== update done $(date -Iseconds) ==="
} >> "$LOG" 2>&1
