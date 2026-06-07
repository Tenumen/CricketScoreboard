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

echo "Repo: $REPO_DIR"

# Install a systemd unit from scripts/, patching the template's default repo
# path if this checkout lives elsewhere than /home/tenumen/scoreboard24.
install_unit() {
    local name="$1"
    local src="$REPO_DIR/scripts/$name"
    local dst="/etc/systemd/system/$name"
    echo "→ installing $dst"
    if [[ "$REPO_DIR" != "/home/tenumen/scoreboard24" ]]; then
        sed -e "s|/home/tenumen/scoreboard24|$REPO_DIR|g" "$src" > "$dst"
    else
        install -m 0644 "$src" "$dst"
    fi
}

# 1. State directory (rollback target + update log live here).
echo "→ creating $STATE_DIR"
install -d -m 0755 "$STATE_DIR"

# 2. Make scripts executable so the HTTP handler can spawn them via bash.
#    The .py mailer is invoked by systemd's ExecStopPost with an explicit
#    python3 interpreter, so the +x is belt-and-braces (also lets the dry-run
#    in setup_mailer_creds.md work without `python3` prefixing).
echo "→ chmod +x scripts/*.sh scripts/*.py"
chmod +x "$REPO_DIR"/scripts/*.sh "$REPO_DIR"/scripts/*.py

# 3. Install the systemd units: the scoreboard wall, the BT adapter boot
#    watchdog, and the BLE bridge. The watchdog is ordered before the bridge so
#    the bridge only starts once a healthy BT adapter is confirmed.
install_unit scoreboard24.service
install_unit bt-adapter-watchdog.service
install_unit playcricket-ble-bridge.service

# 4. Reload + enable. scoreboard24 and the watchdog start now; the bridge is
#    only enabled (not restarted) so a running match isn't interrupted — its new
#    ordering takes effect on the next start/boot.
echo "→ systemctl daemon-reload"
systemctl daemon-reload

echo "→ enabling services"
systemctl enable --now scoreboard24.service
systemctl enable --now bt-adapter-watchdog.service
systemctl enable playcricket-ble-bridge.service

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
