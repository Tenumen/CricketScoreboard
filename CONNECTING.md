# Connecting to the scoreboard Pi by name

The scoreboard Pi announces itself on the local network as **`raspscoreboard.local`**
using mDNS (Bonjour / "zero-config" networking). You do **not** need to know the IP
address the ground's WiFi assigned it — the name finds it automatically, even when the
IP changes between visits.

- **Admin console:** open <http://raspscoreboard.local:8080/> in a browser (admin / AOTVCC)
- **SSH (maintenance):** `ssh tenumen@raspscoreboard.local`

Both the Pi and your device must be on the **same WiFi** as the ground's network.

## Per-device support

| Device | What's needed |
|---|---|
| Android phone/tablet | Works out of the box. |
| iPhone / iPad / Mac | Works out of the box (Bonjour). |
| Windows 10 / 11 | Works out of the box (build 1803+). |
| Older Windows | Install **Bonjour Print Services** from Apple, then it works. |
| Linux laptop | Needs `avahi-daemon` + `libnss-mdns` (`sudo apt install avahi-daemon libnss-mdns`). |

## If the name won't resolve

1. **Turn off any VPN.** A VPN (e.g. NordVPN) routes traffic off the local network and
   blocks the multicast that mDNS relies on — the name will fail even though the Pi is fine.
   This is the most common cause.
2. **Confirm you're on the ground's WiFi**, not mobile data or a different network.
3. **Guest-WiFi "client isolation".** Some venue/guest networks stop devices seeing each
   other. If `raspscoreboard.local` fails for *everyone* on that network but the scoreboard
   itself works, isolation is likely on — there is no client-side fix; use a network without
   isolation, or fall back to the IP for that visit.

## Maintenance notes (not needed by operators)

- The Pi has **WiFi power-save disabled** (NetworkManager `preconfigured` profile,
  `802-11-wireless.powersave=2`) so the radio stays awake and answers mDNS promptly.
  This is the key reliability setting — verify with
  `nmcli -g 802-11-wireless.powersave c show preconfigured` (should read `disable`).
- Avahi is enabled at boot and serves an IPv4 A record:
  `avahi-resolve -4 -n raspscoreboard.local` returns the current IP.
- A `Host raspscoreboard` alias exists in the dev box `~/.ssh/config`, so `ssh raspscoreboard`
  works (VPN off).
- mDNS keeps working when the ground's DHCP hands the Pi a new IP — no reconfiguration needed.
