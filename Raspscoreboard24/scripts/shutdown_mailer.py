#!/usr/bin/env python3
"""Send a digest email when scoreboard24.service stops.

Triggered by ExecStopPost= in scoreboard24.service. Reads credentials from
$CREDENTIALS_DIRECTORY/scoreboard24-mailer (provisioned via
LoadCredentialEncrypted=). Walks discovery.log for UNKNOWN codes since the
service started, and journalctl for warnings+errors from both services.
Sends one digest via Gmail SMTP if anything to report; skips silently
otherwise. Never exits non-zero -- must not block the service stop.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import logging
import os
import pathlib
import re
import smtplib
import subprocess
import sys
from email.message import EmailMessage

LOG = logging.getLogger("shutdown_mailer")

DISCOVERY_LOG = pathlib.Path("/home/tenumen/playcricket_ble_bridge/discovery.log")
SCOREBOARD_UNIT = "scoreboard24.service"
BRIDGE_UNIT = "playcricket-ble-bridge.service"
CREDENTIAL_NAME = "scoreboard24-mailer"
SMTP_TIMEOUT_SEC = 20
JOURNAL_MAX_LINES = 200

UNKNOWN_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+(\w{3})\s+UNKNOWN\b")
RELATIVE_SINCE = re.compile(r"^-(\d+)([hm])$")


def load_credentials() -> dict | None:
    creds_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if not creds_dir:
        LOG.warning("CREDENTIALS_DIRECTORY not set; cannot send")
        return None
    path = pathlib.Path(creds_dir) / CREDENTIAL_NAME
    if not path.exists():
        LOG.warning("credential file %s missing; cannot send", path)
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        LOG.exception("credential file unparseable")
        return None


def get_service_start_time(unit: str) -> dt.datetime:
    fallback = dt.datetime.now().astimezone() - dt.timedelta(hours=1)
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        LOG.exception("systemctl show failed for %s; using 1h fallback", unit)
        return fallback
    if not out or out == "n/a":
        LOG.info("service %s has no ActiveEnterTimestamp; using 1h fallback", unit)
        return fallback
    # systemctl emits "Tue 2026-05-19 14:23:01 BST" -- weekday, date, time, tz:
    # exactly 4 space-separated tokens. The trailing tz abbreviation is
    # locale-dependent and unreliable for strptime, so drop it (keep only the
    # first 3 tokens) and interpret the remainder as local time.
    parts = out.split()
    try:
        naive = dt.datetime.strptime(" ".join(parts[:3]), "%a %Y-%m-%d %H:%M:%S")
        return naive.astimezone()
    except Exception:
        LOG.exception("ActiveEnterTimestamp %r unparseable; using 1h fallback", out)
        return fallback


def parse_discovery_log(path: pathlib.Path, since: dt.datetime) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    if not path.exists():
        LOG.info("discovery log %s absent; no unknown codes to report", path)
        return counts
    try:
        with path.open() as f:
            for line in f:
                m = UNKNOWN_LINE.match(line)
                if not m:
                    continue
                try:
                    ts = dt.datetime.fromisoformat(m.group(1)).astimezone()
                except ValueError:
                    continue
                if ts >= since:
                    counts[m.group(2)] += 1
    except Exception:
        LOG.exception("failed reading discovery log %s", path)
    return counts


def journal_errors(unit: str, since: dt.datetime,
                   max_lines: int = JOURNAL_MAX_LINES) -> list[str]:
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    try:
        out = subprocess.run(
            ["journalctl", "-u", unit, f"--since={since_str}",
             "--priority=warning", "--output=short-iso", "--no-pager"],
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        LOG.exception("journalctl failed for %s", unit)
        return []
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("-- ")]
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _append_block(out: list[str], header: str, lines: list[str]) -> None:
    out.append(header)
    if lines:
        out.extend("  " + ln for ln in lines)
    else:
        out.append("  (none)")
    out.append("")


def compose(since: dt.datetime,
            codes: collections.Counter,
            sb_errs: list[str],
            br_errs: list[str]) -> tuple[str, str]:
    now = dt.datetime.now().astimezone()
    n_codes = sum(codes.values())
    n_errs = len(sb_errs) + len(br_errs)
    subject = f"[scoreboard24] shutdown report -- {n_codes} codes, {n_errs} errors"

    body: list[str] = []
    body.append(
        f"Run window: {since.isoformat(timespec='seconds')}"
        f" -> {now.isoformat(timespec='seconds')}"
    )
    body.append("")

    code_lines = [
        f"{count:>4} x {code}"
        for code, count in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    _append_block(body, "Unknown codes (count x code):", code_lines)
    _append_block(body, "scoreboard24 warnings/errors:", sb_errs)
    _append_block(body, "BLE bridge warnings/errors:", br_errs)

    return subject, "\n".join(body)


def send_via_smtp(creds: dict, subject: str, body: str,
                  timeout: int = SMTP_TIMEOUT_SEC) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = creds["sender"]
    msg["To"] = creds["recipient"]
    msg.set_content(body)
    with smtplib.SMTP(creds["smtp_host"], creds["smtp_port"], timeout=timeout) as s:
        s.starttls()
        s.login(creds["sender"], creds["app_password"])
        s.send_message(msg)


def parse_since_arg(arg: str) -> dt.datetime:
    m = RELATIVE_SINCE.match(arg)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = dt.timedelta(hours=n) if unit == "h" else dt.timedelta(minutes=n)
        return dt.datetime.now().astimezone() - delta
    return dt.datetime.fromisoformat(arg).astimezone()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since",
                        help="Override start time (-Nh, -Nm, or ISO datetime)")
    parser.add_argument("--force-send", action="store_true",
                        help="Send even if there is nothing to report")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="shutdown_mailer: %(message)s",
                        stream=sys.stderr)

    try:
        creds = load_credentials()
        if creds is None:
            return 0

        since = (parse_since_arg(args.since) if args.since
                 else get_service_start_time(SCOREBOARD_UNIT))
        LOG.info("run window since %s", since.isoformat(timespec="seconds"))

        codes = parse_discovery_log(DISCOVERY_LOG, since)
        sb_errs = journal_errors(SCOREBOARD_UNIT, since)
        br_errs = journal_errors(BRIDGE_UNIT, since)

        if not codes and not sb_errs and not br_errs and not args.force_send:
            LOG.info("nothing to report; skipping email")
            return 0

        subject, body = compose(since, codes, sb_errs, br_errs)
        send_via_smtp(creds, subject, body)
        LOG.info("shutdown report emailed to %s", creds["recipient"])
    except Exception:
        LOG.exception("mailer failed (non-fatal)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
