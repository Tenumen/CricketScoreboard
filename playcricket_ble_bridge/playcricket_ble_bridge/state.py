"""Accumulate Play-Cricket Scorer BLE tokens into a MatchDetail-shaped state.

Each token from the phone is an idempotent update: BTS245/3 means "the
current innings stands at 245 for 3", not "add 245/3". The accumulator
applies one token at a time under a lock, bumps a generation counter so
HTTP callers can detect change, and exposes a snapshot for serialisation.

Innings boundary heuristic: the first time we see a BTT (batting team
target) or the first BTN that differs from the recorded batting team
name, we open innings_number=2. The phone has already done the
book-keeping; we just mirror it.

Match-over detection is intentionally deferred — no single token reliably
signals "match complete". The discovery log captures everything received
at the end of a real match so we can map it in a follow-up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import List, Optional

from . import tokens as T


@dataclass
class Bat:
    position: int = 1
    batsman_name: str = ""
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    how_out: str = ""           # "" while at the crease, dismissal name once out
    fielder_name: str = ""
    bowler_name: str = ""


@dataclass
class Fow:
    runs: int = 0
    wickets: int = 0
    batsman_out_name: str = ""
    how_out: str = ""           # decoded LWD value


@dataclass
class Innings:
    innings_number: int = 1
    team_batting_name: str = ""
    runs: int = 0
    wickets: int = 0
    overs: str = "0.0"           # "32.3"
    revised_target_runs: int = 0
    bat: List[Bat] = field(default_factory=lambda: [Bat(position=1), Bat(position=2)])
    fow: List[Fow] = field(default_factory=list)


@dataclass
class MatchState:
    id: int = 9000001
    home_team_name: str = ""
    away_team_name: str = ""
    home_team_id: int = 0
    away_team_id: int = 0
    home_club_id: int = 0
    away_club_id: int = 0
    status: str = "New"
    no_of_overs: int = 20
    result: str = ""
    result_description: str = ""
    match_date: str = ""
    innings: List[Innings] = field(default_factory=lambda: [Innings(innings_number=1)])


def _parse_overs(value: str) -> str:
    """Normalise the OVB value to 'overs.balls'. Bare integer means '.0'."""
    value = value.strip()
    if not value:
        return "0.0"
    if "." in value:
        return value
    return f"{value}.0"


def _parse_score(value: str) -> tuple[int, int]:
    """BTS value: '245/3' (full) or '245' (pairs cricket, no wicket data)."""
    if "/" in value:
        runs, wkts = value.split("/", 1)
        return (int(runs or 0), int(wkts or 0))
    return (int(value or 0), 0)


class MatchAccumulator:
    """Thread-safe holder for MatchState. apply() mutates under a lock and
    bumps the generation counter; snapshot() returns the current state."""

    def __init__(self, our_club_id: int = 0):
        self._lock = RLock()
        self._state = MatchState()
        # Pretend our club is the home side so the C++ chasing logic resolves.
        # Set via config so the wall labels "home/opponent" correctly.
        self._state.home_club_id = our_club_id
        self._generation = 0
        self._unknown_codes: dict[str, int] = {}

    @property
    def generation(self) -> int:
        return self._generation

    def snapshot(self) -> MatchState:
        """Return the current state. Caller must not mutate."""
        with self._lock:
            return self._state

    def unknown_codes(self) -> dict[str, int]:
        with self._lock:
            return dict(self._unknown_codes)

    def apply(self, code: str, value: str) -> bool:
        """Apply one (code, value) update. Returns True if state changed."""
        with self._lock:
            if not T.is_known(code):
                self._unknown_codes[code] = self._unknown_codes.get(code, 0) + 1
                return False
            handler = _HANDLERS.get(code)
            if handler is None:
                return False
            changed = handler(self._state, value)
            if changed:
                self._generation += 1
            return changed


# ---------- token handlers ----------------------------------------------------
#
# Each handler returns True if it changed state. Handlers are intentionally
# tolerant of malformed values (the BLE peripheral has already accepted them)
# and idempotent.

def _current_innings(s: MatchState) -> Innings:
    return s.innings[-1]


def _ensure_second_innings(s: MatchState, batting_team_name: str) -> None:
    """Open innings 2 if we're still on innings 1 and the batting side has
    flipped. Called from BTN/BTT handlers."""
    cur = _current_innings(s)
    if cur.innings_number == 1 and cur.team_batting_name and \
       batting_team_name and batting_team_name != cur.team_batting_name:
        s.innings.append(Innings(innings_number=2, team_batting_name=batting_team_name))


def _h_bts(s: MatchState, value: str) -> bool:
    runs, wkts = _parse_score(value)
    inn = _current_innings(s)
    if inn.runs == runs and inn.wickets == wkts:
        return False
    inn.runs = runs
    inn.wickets = wkts
    s.status = "In Progress"
    return True


def _h_ovb(s: MatchState, value: str) -> bool:
    overs = _parse_overs(value)
    inn = _current_innings(s)
    if inn.overs == overs:
        return False
    inn.overs = overs
    s.status = "In Progress"
    return True


def _h_ovr(s: MatchState, value: str) -> bool:
    # Overs remaining — only useful at innings start to know the format.
    try:
        rem = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    # Total = balls bowled / 6 + remaining.
    legal_balls = int(inn.overs.split(".")[0]) * 6 + int(inn.overs.split(".")[-1] or 0)
    proposed_total = (legal_balls + 5) // 6 + rem
    if proposed_total and s.no_of_overs != proposed_total:
        s.no_of_overs = proposed_total
        return True
    return False


def _h_cov(s: MatchState, value: str) -> bool:
    # Fired at end of each over; trailing 'W' marks a wicket-ending over. We
    # rely on BTS/B1S/B2S to carry the actual numbers, so COV alone is a
    # no-op for the rendered state.
    return False


def _h_ftn(s: MatchState, value: str) -> bool:
    name = value.strip()
    if not name:
        return False
    cur = _current_innings(s)
    # Fielding team = the side NOT batting in this innings.
    if cur.team_batting_name == name:
        return False
    if cur.innings_number == 1 and not s.home_team_name and not s.away_team_name:
        # First innings: assume we (home) batting first by default; the BTN
        # handler will correct this if BTN tells us otherwise.
        s.away_team_name = name
        return True
    if cur.innings_number == 1:
        # Already learnt one side; this fills in the other.
        if cur.team_batting_name == s.home_team_name:
            if s.away_team_name != name:
                s.away_team_name = name
                return True
        else:
            if s.home_team_name != name:
                s.home_team_name = name
                return True
    return False


def _h_btn(s: MatchState, value: str) -> bool:
    name = value.strip()
    if not name:
        return False
    _ensure_second_innings(s, name)
    cur = _current_innings(s)
    changed = False
    if cur.team_batting_name != name:
        cur.team_batting_name = name
        changed = True
    # Mirror onto match-level team names so the C++ side has labels.
    if cur.innings_number == 1:
        if s.home_team_name != name:
            s.home_team_name = name
            changed = True
    elif cur.innings_number == 2:
        # Innings 2 batting side = the OTHER team. If we haven't recorded
        # them yet, fill in.
        if s.away_team_name and s.away_team_name != name:
            # away_team_name was a guess from FTN — name now confirmed for
            # innings 2; nothing to do here.
            pass
        elif not s.away_team_name:
            s.away_team_name = name
            changed = True
    return changed


def _h_btt(s: MatchState, value: str) -> bool:
    try:
        target = int(value or 0)
    except ValueError:
        return False
    if target <= 0:
        return False
    # Existence of a target implies a 2nd innings is in progress. The phone
    # may have sent BTT before BTN, in which case we open innings 2 now using
    # whatever batting-team name we have (will be corrected on the next BTN).
    cur = _current_innings(s)
    if cur.innings_number == 1:
        s.innings.append(Innings(innings_number=2,
                                 team_batting_name=cur.team_batting_name or ""))
        cur = _current_innings(s)
        # Also flag the first innings as having activity even if no BTS was
        # seen (defensive).
        if s.innings[0].runs == 0 and s.innings[0].overs == "0.0":
            s.innings[0].runs = max(target - 1, 1)
    if cur.revised_target_runs != target:
        cur.revised_target_runs = target
        return True
    return False


def _h_rrq(s: MatchState, value: str) -> bool:
    # Informational; not consumed by the wall today.
    return False


def _h_rrr(s: MatchState, value: str) -> bool:
    # Informational; not consumed by the wall today.
    return False


def _h_batter_score(idx: int, s: MatchState, value: str) -> bool:
    try:
        runs = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    if inn.bat[idx].runs == runs:
        return False
    inn.bat[idx].runs = runs
    return True


def _h_batter_balls(idx: int, s: MatchState, value: str) -> bool:
    try:
        balls = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    if inn.bat[idx].balls == balls:
        return False
    inn.bat[idx].balls = balls
    return True


def _h_batter_strike(idx: int, s: MatchState, value: str) -> bool:
    # B1K1 / B2K1 — striker indicator. The C++ side draws a '*' next to the
    # striker, but the current renderer doesn't read this directly — kept
    # for future use. Treat as no-op for now to avoid spurious generation
    # bumps on every ball.
    return False


def _h_lwk(s: MatchState, value: str) -> bool:
    try:
        team_score = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    # Last wicket: append/update a Fow entry for the most recent dismissal.
    if not inn.fow or inn.fow[-1].runs != team_score:
        inn.fow.append(Fow(runs=team_score, wickets=inn.wickets or len(inn.fow) + 1))
        return True
    return False


def _h_lws(s: MatchState, value: str) -> bool:
    # Out-batter's score — informational; not surfaced on the wall today.
    return False


def _h_lwd(s: MatchState, value: str) -> bool:
    code = value.strip()
    name = T.DISMISSAL_NAMES.get(code, code)
    inn = _current_innings(s)
    if not inn.fow:
        return False
    if inn.fow[-1].how_out == name:
        return False
    inn.fow[-1].how_out = name
    return True


_HANDLERS = {
    "BTS": _h_bts,
    "OVB": _h_ovb,
    "OVR": _h_ovr,
    "COV": _h_cov,
    "FTN": _h_ftn,
    "BTN": _h_btn,
    "BTT": _h_btt,
    "RRQ": _h_rrq,
    "RRR": _h_rrr,
    "B1S": lambda s, v: _h_batter_score(0, s, v),
    "B1B": lambda s, v: _h_batter_balls(0, s, v),
    "B1K": lambda s, v: _h_batter_strike(0, s, v),
    "B2S": lambda s, v: _h_batter_score(1, s, v),
    "B2B": lambda s, v: _h_batter_balls(1, s, v),
    "B2K": lambda s, v: _h_batter_strike(1, s, v),
    "LWK": _h_lwk,
    "LWS": _h_lws,
    "LWD": _h_lwd,
}
