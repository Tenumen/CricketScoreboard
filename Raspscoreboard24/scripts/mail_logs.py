#!/usr/bin/env python3
"""Email the BLE bridge's logs off the Pi on demand.

Triggered by the admin-console "Email match logs" button (debug_server.cpp spawns
mail_logs.sh, which runs this). Reuses the shutdown mailer's encrypted credential
(scoreboard24-mailer, provisioned via LoadCredentialEncrypted=) and attaches every
*.log in the bridge directory -- chiefly discovery.log, the append-only record of
every received BLE token, which is what we need to diagnose match-day issues.

Each attachment is capped to its last MAX_ATTACH_BYTES so a long-lived
discovery.log can't blow past the SMTP size limit; the tail is exactly the most
recent match. Never exits non-zero -- the button is fire-and-forget and the inbox
is the real confirmation.
"""

from __future__ import annotations

import datetime as dt
import logging
import pathlib
import smtplib
import sys
from email.message import EmailMessage

# Reuse the shutdown mailer's credential loading so there is one place that
# knows the credential name and format. Runs from the scripts/ dir, which is on
# sys.path[0], so this import resolves when invoked directly.
from shutdown_mailer import load_credentials

LOG = logging.getLogger("mail_logs")

BRIDGE_DIR = pathlib.Path("/home/tenumen/playcricket_ble_bridge")
SMTP_TIMEOUT_SEC = 30
MAX_ATTACH_BYTES = 5 * 1024 * 1024  # 5 MiB tail per file


def collect_logs(bridge_dir: pathlib.Path) -> list[pathlib.Path]:
    """Every *.log in the bridge dir, discovery.log first, largest-recent next."""
    if not bridge_dir.exists():
        return []
    logs = sorted(bridge_dir.glob("*.log"))
    logs.sort(key=lambda p: (p.name != "discovery.log", p.name))
    return logs


def read_tail(path: pathlib.Path, max_bytes: int) -> tuple[bytes, bool]:
    """Return (data, truncated). Reads at most max_bytes from the end of the file."""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            return f.read(), True
        return f.read(), False


def compose(creds: dict, logs: list[pathlib.Path]) -> EmailMessage:
    now = dt.datetime.now().astimezone()
    msg = EmailMessage()
    msg["Subject"] = f"[scoreboard24] match logs -- {now.strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = creds["sender"]
    msg["To"] = creds["recipient"]

    body: list[str] = [
        f"Bridge logs from the scoreboard, sent {now.isoformat(timespec='seconds')}.",
        "",
    ]
    if not logs:
        body.append(f"No *.log files found in {BRIDGE_DIR}.")
        msg.set_content("\n".join(body))
        return msg

    attachments: list[tuple[pathlib.Path, bytes]] = []
    for path in logs:
        try:
            data, truncated = read_tail(path, MAX_ATTACH_BYTES)
        except Exception:
            LOG.exception("failed reading %s", path)
            body.append(f"  {path.name}: (unreadable)")
            continue
        note = " (tail, truncated)" if truncated else ""
        body.append(f"  {path.name}: {len(data)} bytes{note}")
        attachments.append((path, data))

    # set_content() must run BEFORE any add_attachment() call: EmailMessage
    # refuses set_content() once add_attachment() has made it multipart, which
    # is what silently broke every send with a *.log file present (always,
    # in practice) -- the button reported success but nothing was ever sent.
    msg.set_content("\n".join(body))
    for path, data in attachments:
        msg.add_attachment(data, maintype="text", subtype="plain",
                           filename=path.name)
    return msg


def send(creds: dict, msg: EmailMessage, timeout: int = SMTP_TIMEOUT_SEC) -> None:
    with smtplib.SMTP(creds["smtp_host"], creds["smtp_port"], timeout=timeout) as s:
        s.starttls()
        s.login(creds["sender"], creds["app_password"])
        s.send_message(msg)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="mail_logs: %(message)s", stream=sys.stderr)
    try:
        creds = load_credentials()
        if creds is None:
            LOG.warning("no mailer credentials; cannot send")
            return 0
        logs = collect_logs(BRIDGE_DIR)
        msg = compose(creds, logs)
        send(creds, msg)
        LOG.info("emailed %d log file(s) to %s", len(logs), creds["recipient"])
    except Exception:
        LOG.exception("mail_logs failed (non-fatal)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
