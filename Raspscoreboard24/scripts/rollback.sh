#!/usr/bin/env bash
# rollback.sh — restore the previous binary + reset the source tree to the
# commit it was built from, then restart the service.
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

    echo "=== restarting $(date -Iseconds) ==="
    systemctl restart scoreboard24.service

    echo "=== rollback done $(date -Iseconds) ==="
} >> "$LOG" 2>&1
