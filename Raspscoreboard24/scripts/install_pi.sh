#!/usr/bin/env bash
# install_pi.sh — one-time Pi-side setup for the auto-update workflow.
#
#   sudo bash scripts/install_pi.sh   (run from inside the scoreboard24 repo)
#
# Idempotent: safe to re-run.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/install_pi.sh" >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="/var/lib/scoreboard24"
UNIT_SRC="$REPO_DIR/scripts/scoreboard24.service"
UNIT_DST="/etc/systemd/system/scoreboard24.service"

echo "Repo: $REPO_DIR"

# 1. State directory (rollback target + update log live here).
echo "→ creating $STATE_DIR"
install -d -m 0755 "$STATE_DIR"

# 2. Make scripts executable so the HTTP handler can spawn them via bash.
#    The .py mailer is invoked by systemd's ExecStopPost with an explicit
#    python3 interpreter, so the +x is belt-and-braces (also lets the dry-run
#    in setup_mailer_creds.md work without `python3` prefixing).
echo "→ chmod +x scripts/*.sh scripts/*.py"
chmod +x "$REPO_DIR"/scripts/*.sh "$REPO_DIR"/scripts/*.py

# 3. Install the systemd unit. Patch WorkingDirectory/ExecStart if the repo
#    isn't at /home/tenumen/scoreboard24 (the template default).
echo "→ installing $UNIT_DST"
if [[ "$REPO_DIR" != "/home/tenumen/scoreboard24" ]]; then
    sed -e "s|/home/tenumen/scoreboard24|$REPO_DIR|g" "$UNIT_SRC" > "$UNIT_DST"
else
    install -m 0644 "$UNIT_SRC" "$UNIT_DST"
fi

# 4. Reload + enable + start.
echo "→ systemctl daemon-reload"
systemctl daemon-reload

echo "→ systemctl enable --now scoreboard24.service"
systemctl enable --now scoreboard24.service

# 5. Boot-speedup (idempotent). Nothing on this Pi needs the network to be
#    "online" before it starts — the scoreboard talks to the bridge over
#    localhost and the bridge serves only on 127.0.0.1 — and the box runs
#    headless. So we strip the boot-time waits that bought us nothing:
#      * NetworkManager-wait-online blocked ~10s waiting for WiFi/DHCP (made
#        worse by the unplugged eth0 autoconnect) and gated everything behind
#        network-online.target. WiFi still associates in the background.
#      * ModemManager probes for a (non-existent) cellular modem, ~2s.
#      * graphical.target pulled in lightdm/X with no display to drive.
#    Net effect measured on a Pi 3B: ~23.7s -> ~15.3s boot, panel lit ~10s
#    sooner. Revert any of these with the matching enable/set-default command.
echo "→ boot speedup: disable network-online wait + ModemManager, drop desktop"
systemctl disable NetworkManager-wait-online.service 2>/dev/null || true
systemctl disable ModemManager.service              2>/dev/null || true
if [[ "$(systemctl get-default)" != "multi-user.target" ]]; then
    systemctl set-default multi-user.target
fi

# 6. Status hint.
echo
echo "Done. Useful commands:"
echo "  systemctl status scoreboard24"
echo "  journalctl -u scoreboard24 -f"
echo
echo "Admin console (set the password in config.json first):"
echo "  http://raspscoreboard.local:8080/    user: admin"
echo
echo "If the update or rollback button fails (e.g. new binary crashes on boot)"
echo "and the admin console becomes unreachable, run this locally:"
echo "  sudo bash $REPO_DIR/scripts/rollback.sh"
