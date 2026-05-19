"""Play-Cricket Scorer 'generic external scoreboard' BLE token catalogue and
parser.

Each notification from the phone is a single ASCII string: the first three
bytes are an item code, the rest is the value. Examples:

    BTS245/3        -> ("BTS", "245/3")
    OVB32.3         -> ("OVB", "32.3")
    B1K1            -> ("B1K", "1")
    COVW            -> ("COV", "W")
    BTNAston on Trent 1st XI -> ("BTN", "Aston on Trent 1st XI")
    LWDlbw          -> ("LWD", "lbw")

Sources: buildyourownscoreboard.wordpress.com and the Medium article by Andy
Smy (Play-Cricket Bluetooth External Scoreboards). The protocol is
community-documented, not formally specified, so unknown codes are
preserved verbatim in the parser output and logged for later mapping.
"""
from __future__ import annotations

from typing import Optional, Tuple


# BLE GATT identifiers used by Play-Cricket Scorer for the "Generic"
# external scoreboard. The Pi advertises a peripheral implementing this
# service; the phone connects as central and writes notifications.
SERVICE_UUID        = "5a0d6a15-b664-4304-8530-3a0ec53e5bc1"
CHARACTERISTIC_UUID = "df531f62-fc0b-40ce-81b2-32a6262ea440"


# Three-letter token codes we recognise. Comments describe the value shape.
TOKEN_CATALOGUE = {
    "BTS": "Batting side's total score, runs/wickets or runs (pairs cricket)",
    "OVB": "Over.ball count, e.g. '32.3' or '5' (= 5.0)",
    "OVR": "Overs remaining (numeric)",
    "COV": "Commence over; trailing digit = runs in last over, 'W' = wicket",
    "FTN": "Fielding team name (text)",
    "BTN": "Batting team name (text)",
    "BTT": "Batting team target (numeric)",
    "RRQ": "Runs required (numeric)",
    "RRR": "Run rate required (decimal)",
    "B1S": "Batter 1 runs",
    "B1B": "Batter 1 balls faced",
    "B1K": "Batter 1 on strike (1/0)",
    "B2S": "Batter 2 runs",
    "B2B": "Batter 2 balls faced",
    "B2K": "Batter 2 on strike (1/0)",
    "LWK": "Last wicket — team score when it fell",
    "LWS": "Last wicket batter's score",
    "LWD": "Last wicket decision (b/lbw/c/ro/hw/ht/to/of/rt)",
}

DISMISSAL_NAMES = {
    "b":   "bowled",
    "lbw": "lbw",
    "c":   "caught",
    "ro":  "run out",
    "hw":  "hit wicket",
    "ht":  "hit ball twice",
    "to":  "timed out",
    "of":  "obstructing the field",
    "rt":  "retired",
}


def parse_frame(payload) -> Optional[Tuple[str, str]]:
    """Decode a single BLE notification payload into (code, value).

    Accepts bytes, bytearray, or str. Returns None for empty/short frames.
    Whitespace surrounding the value is preserved (BTN values can legitimately
    contain trailing spaces in some clubs' team names).

    Unknown three-letter codes are returned as-is; the accumulator decides
    whether to apply them and the BLE peripheral logs them for later mapping.
    """
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            text = bytes(payload).decode("utf-8", errors="replace")
        except Exception:
            return None
    else:
        text = str(payload)
    text = text.strip("\r\n")
    if len(text) < 3:
        return None
    code  = text[:3]
    value = text[3:]
    if not code.isascii():
        return None
    return (code, value)


def is_known(code: str) -> bool:
    return code in TOKEN_CATALOGUE
