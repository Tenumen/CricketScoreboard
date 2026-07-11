#!/usr/bin/env bash
# rollback.sh — restore the previous C++ binary + reset the source tree to the
# commit it was built from, redeploy the bridge from that same commit, then
# restart both services. The inverse of update.sh, so it reverts BOTH halves.
#
# Spawned (detached) by the admin-console "Roll back" button. Also runnable
# directly: `sudo bash scripts/rollback.sh`.

set -euo pipefail

# Runs as root (see update.sh) against a tenumen-owned repo; trust all repos so
# `git reset --hard` below doesn't abort with "detected dubious ownership".
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0='*'

REPO_DIR="${REPO_DIR:-/home/tenumen/scoreboard24}"
BRIDGE_RUN_DIR="${BRIDGE_RUN_DIR:-/home/tenumen/playcricket_ble_bridge}"
BRIDGE_SERVICE="playcricket-ble-bridge.service"
STATE_DIR="/var/lib/scoreboard24"
LOG="$STATE_DIR/last_update.log"

if [[ ! -f "$STATE_DIR/scoreboard24.prev" || ! -f "$STATE_DIR/prev_commit" ]]; then
    echo "rollback target missing: run update.sh at least once first" >&2
    exit 1
fi

{
    echo
    echo "=== rollback started $(date -Iseconds) ==="
    cd "$REPO_DIR"

    cp "$STATE_DIR/scoreboard24.prev" scoreboard24
    PREV_COMMIT=$(cat "$STATE_DIR/prev_commit")
    echo "restoring binary + git reset --hard $PREV_COMMIT"
    git reset --hard "$PREV_COMMIT"

    echo "=== restarting scoreboard24 $(date -Iseconds) ==="
    systemctl restart scoreboard24.service

    # Redeploy the bridge from the now-reverted repo copy and restart it, so the
    # bridge rolls back in lockstep with the C++ binary (mirrors update.sh step 5).
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    BRIDGE_SRC="$REPO_ROOT/playcricket_ble_bridge/playcricket_ble_bridge"
    BRIDGE_DST="$BRIDGE_RUN_DIR/playcricket_ble_bridge"
    if [[ -d "$BRIDGE_SRC" && -d "$BRIDGE_DST" ]]; then
        echo "=== reverting bridge: $BRIDGE_SRC -> $BRIDGE_DST ==="
        rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
            "$BRIDGE_SRC/" "$BRIDGE_DST/"
        chown -R tenumen:tenumen "$BRIDGE_DST"
        echo "=== restarting bridge $(date -Iseconds) ==="
        systemctl restart "$BRIDGE_SERVICE"
    else
        echo "WARN: bridge src/dst missing — skipping bridge revert"
    fi

    echo "=== rollback done $(date -Iseconds) ==="
} >> "$LOG" 2>&1
