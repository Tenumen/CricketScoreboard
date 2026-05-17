#!/usr/bin/env bash
# Convenience launcher for mock_playcricket.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .venv ]]; then . .venv/bin/activate; fi
exec python -m mock_playcricket "$@"
