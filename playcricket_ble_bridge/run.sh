#!/usr/bin/env bash
# Convenience launcher for playcricket_ble_bridge.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .venv ]]; then . .venv/bin/activate; fi
exec python -m playcricket_ble_bridge "$@"
