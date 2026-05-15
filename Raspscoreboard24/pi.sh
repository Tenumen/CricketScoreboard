#!/usr/bin/env bash
# pi.sh — helper to start/stop scoreboard24 on the Pi
# Usage:
#   ./pi.sh start [scoreboard|calibrate|calibrate-all]
#   ./pi.sh stop

set -euo pipefail

PI="tenumen@192.168.1.130"
REMOTE_DIR="~/scoreboard24"
BINARY="scoreboard24"
LOG="/tmp/scoreboard24.log"

_stop() {
    echo "Stopping $BINARY on $PI (SIGTERM)..."
    ssh "$PI" "
        if pgrep $BINARY > /dev/null 2>&1; then
            sudo kill -TERM \$(pgrep $BINARY)
            echo 'Sent SIGTERM.'
        else
            echo '$BINARY is not running.'
        fi
    "
}

usage() {
    echo "Usage:"
    echo "  $0 start [scoreboard|calibrate|calibrate-all|calibrate-quads]"
    echo "  $0 stop"
    echo ""
    echo "Patterns:"
    echo "  scoreboard       (default) render scoreboard display"
    echo "  calibrate        sequential panel-by-panel calibration"
    echo "  calibrate-all    all 24 panels labelled simultaneously"
    echo "  calibrate-quads  6 colour squares at 4-panel junctions"
    exit 1
}

VERB="${1:-}"

case "$VERB" in
    start)
        PATTERN="${2:-scoreboard}"

        case "$PATTERN" in
            scoreboard)      FLAGS="" ;;
            calibrate)       FLAGS="--calibrate" ;;
            calibrate-all)   FLAGS="--calibrate=all" ;;
            calibrate-quads) FLAGS="--calibrate=quads" ;;
            *)
                echo "Error: unknown pattern '$PATTERN'."
                echo "Valid patterns: scoreboard, calibrate, calibrate-all, calibrate-quads"
                exit 1
                ;;
        esac

        _stop

        echo "Starting '$PATTERN' on $PI..."
        ssh "$PI" "
            cd $REMOTE_DIR
            nohup sudo ./$BINARY $FLAGS > $LOG 2>&1 &
            disown
        "
        echo "Started. Log: $PI:$LOG"
        ;;

    stop)
        _stop
        ;;

    *)
        usage
        ;;
esac
