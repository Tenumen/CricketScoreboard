#!/usr/bin/env bash
# update.sh — pull latest commit, rebuild the C++ scoreboard, deploy the Python
# BLE bridge, and restart BOTH services. Snapshots the previous binary + commit
# hash so rollback.sh can revert.
#
# The one git pull updates the whole repo, so both halves ship from the same
# commit. The bridge is not compiled — its package is rsynced from the repo copy
# into the running bridge dir and its service restarted. NOTE: restarting the
# bridge drops any live BLE link and clears in-progress score state, so only run
# this between matches (the admin button warns the operator of exactly that).
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
# Running Python bridge dir (systemd WorkingDirectory of playcricket-ble-bridge).
# Its inner package is replaced from the repo copy on each update.
BRIDGE_RUN_DIR="${BRIDGE_RUN_DIR:-/home/tenumen/playcricket_ble_bridge}"
BRIDGE_SERVICE="playcricket-ble-bridge.service"
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

    # 4. Restart the C++ scoreboard via systemd. KillMode=process means this
    #    script (a separate process tree from scoreboard24) keeps running through
    #    the restart, so it can go on to deploy the bridge below.
    PHASE=restart; status running restart
    echo "=== restarting scoreboard24 $(date -Iseconds) ==="
    systemctl restart scoreboard24.service

    # 5. Deploy the Python BLE bridge from the just-pulled repo copy and restart
    #    it. The bridge isn't built — we mirror its package into the running dir.
    #    Resolve the repo root from git (robust to REPO_DIR being a symlink into
    #    a subdir) so we always sync the copy that matches the pulled commit.
    PHASE=bridge; status running bridge
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    BRIDGE_SRC="$REPO_ROOT/playcricket_ble_bridge/playcricket_ble_bridge"
    BRIDGE_DST="$BRIDGE_RUN_DIR/playcricket_ble_bridge"
    if [[ -d "$BRIDGE_SRC" && -d "$BRIDGE_DST" ]]; then
        echo "=== deploying bridge: $BRIDGE_SRC -> $BRIDGE_DST ==="
        rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
            "$BRIDGE_SRC/" "$BRIDGE_DST/"
        # The repo tree is root-owned after root's git pull; the bridge runs as
        # 'tenumen', so hand the package back so a later manual sync/edit works.
        chown -R tenumen:tenumen "$BRIDGE_DST"
        echo "=== restarting bridge $(date -Iseconds) ==="
        systemctl restart "$BRIDGE_SERVICE"
    else
        echo "WARN: bridge src/dst missing (src=$BRIDGE_SRC dst=$BRIDGE_DST) — skipping bridge deploy"
    fi

    status done ""
    echo "=== update done $(date -Iseconds) ==="
} >> "$LOG" 2>&1
