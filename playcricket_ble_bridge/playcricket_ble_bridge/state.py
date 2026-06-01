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


# Default fragment used to recognise our own club among the two team names
# the app sends (BTN = batting team, FTN = fielding team). Overridable via
# --our-team-name. It only decides which real name maps to the home slot;
# the displayed names always come from the app.
DEFAULT_OUR_TEAM_HINT = "Aston"


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
    team_fielding_name: str = ""
    runs: int = 0
    wickets: int = 0
    overs: str = "0.0"           # "32.3"
    revised_target_runs: int = 0
    bat: List[Bat] = field(default_factory=lambda: [Bat(position=1), Bat(position=2)])
    fow: List[Fow] = field(default_factory=list)

    # COV-derived running tallies. The Play-Cricket Scorer app sometimes
    # skips BTS / OVB updates between balls (it only refreshes them on
    # certain events), but COV — the ball-by-ball over summary — is sent
    # every single ball. We parse it as a fallback so the wall never lags.
    _legal_balls_at_over_start: int = 0
    _runs_at_over_start:        int = 0
    _prev_cov_balls:            int = 0
    # Per-batter run derivation. The app only sends B*S at the connection
    # snapshot; subsequent balls arrive via COV + B*K (strike). We attribute
    # each new ball's runs to whichever batter B*K marks as on-strike at the
    # moment the ball arrives. `_cov_balls_attributed` keeps us idempotent.
    _striker_idx:           int = 0   # 0 = bat[0] facing, 1 = bat[1] facing
    _cov_balls_attributed:  int = 0


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
    players_per_side: int = 11   # all-out = players_per_side - 1 wickets
    result: str = ""
    result_description: str = ""
    result_manual: bool = False  # operator forced/locked the result; auto-infer won't touch it
    match_date: str = ""
    innings: List[Innings] = field(default_factory=lambda: [Innings(innings_number=1)])

    # Monotonic per-ball / per-wicket counters consumed by the C++ scoreboard
    # to trigger event splashes. Bumped from _h_cov / _h_lwk. The runs/wicket
    # flag describe only the most recent ball (or wicket); older balls are
    # not retained here.
    last_ball_id:        int  = 0
    last_ball_runs:      int  = 0
    last_ball_is_wicket: bool = False
    last_wicket_id:      int  = 0

    # Non-serialised: fragment that identifies our club so its real (app-sent)
    # name maps to the home slot. Set from --our-team-name at construction.
    _our_team_hint: str = DEFAULT_OUR_TEAM_HINT


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


def _parse_cov_balls(value: str) -> list[int]:
    """Parse a COV ball-by-ball summary into a list of per-ball run values.

    Each entry is the number of runs scored off that delivery:
      '.'        ->  0
      digit(s)   ->  that many
      'W'        ->  0 (wicket — counted via LWK/LWD elsewhere)
      anything else -> 0 (best-effort; flagged for review in discovery.log)

    Empty / whitespace-only string returns []. List length = balls in the
    over so far.
    """
    out: list[int] = []
    for tok in value.strip().split():
        if tok == ".":
            out.append(0)
        elif tok.isdigit():
            out.append(int(tok))
        elif tok.upper().startswith("W"):
            out.append(0)
        else:
            out.append(0)
    return out


def _parse_cov(value: str) -> tuple[int, int]:
    """Aggregate form of _parse_cov_balls: returns (balls, runs)."""
    balls_list = _parse_cov_balls(value)
    return (len(balls_list), sum(balls_list))


def _parse_cov_balls_meta(value: str) -> list[tuple[int, bool]]:
    """Per-ball (runs, is_wicket) parse of the COV value. Wicket balls map to
    (0, True); everything else mirrors _parse_cov_balls but carries the flag."""
    out: list[tuple[int, bool]] = []
    for tok in value.strip().split():
        if tok == ".":
            out.append((0, False))
        elif tok.isdigit():
            out.append((int(tok), False))
        elif tok.upper().startswith("W"):
            out.append((0, True))
        else:
            out.append((0, False))
    return out


def _legal_balls_from_overs(overs: str) -> int:
    """Convert 'X.Y' overs notation to integer legal balls."""
    if "." not in overs:
        return int(overs or 0) * 6
    o, b = overs.split(".", 1)
    return int(o or 0) * 6 + int(b or 0)


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def compute_result(s: MatchState, force: bool = False):
    """Infer the match result from the 2nd-innings score.

    The Play-Cricket Scorer BLE feed never sends a result or "match over"
    token, so we derive it. Returns (result_code, result_description) once the
    match is decided, else None. The 2nd innings is the chase. With force=True
    the "innings complete" gate is dropped: the current chase state is treated
    as final (used by the operator's "Match finished" override).
    """
    if len(s.innings) < 2:
        return ("C", "Match complete") if force else None

    inn1, inn2 = s.innings[0], s.innings[1]
    target = inn2.revised_target_runs or (inn1.runs + 1)
    wkts_all_out = max(s.players_per_side - 1, 1)
    team_first = inn1.team_batting_name or "Team 1"
    team_chase = inn2.team_batting_name or "Team 2"

    def chase_win() -> tuple[str, str]:
        in_hand = max(wkts_all_out - inn2.wickets, 0)
        return ("W", f"{team_chase} won by {_plural(in_hand, 'wicket')}")

    # Chase succeeds: side batting second wins, by wickets in hand.
    if inn2.runs >= target:
        return chase_win()

    chase_complete = (
        inn2.wickets >= wkts_all_out
        or _legal_balls_from_overs(inn2.overs) >= s.no_of_overs * 6
    )
    if chase_complete or force:
        margin = (target - 1) - inn2.runs
        if margin > 0:
            return ("W", f"{team_first} won by {_plural(margin, 'run')}")
        if margin == 0:
            return ("T", "Match tied")
        return chase_win()  # margin < 0 unreachable above, but safe under force

    return None


class MatchAccumulator:
    """Thread-safe holder for MatchState. apply() mutates under a lock and
    bumps the generation counter; snapshot() returns the current state."""

    def __init__(self, our_club_id: int = 0,
                 our_team_name: str = DEFAULT_OUR_TEAM_HINT):
        self._lock = RLock()
        self._state = MatchState()
        self._state.home_club_id   = our_club_id
        # home/away team names are learned from the app's BTN/FTN tokens; only
        # the hint that picks which side is "ours" is configured here.
        self._state._our_team_hint = (our_team_name or "").strip()
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
                self._maybe_autoresult()
            return changed

    def _maybe_autoresult(self) -> None:
        """Set result/result_description if the score now decides the match.
        Sticky: once a result is set (auto or manual) it is left in place until
        reopen() clears it. Caller must hold the lock."""
        s = self._state
        if s.result_manual or s.result:
            return
        res = compute_result(s)
        if res is not None:
            s.result, s.result_description = res

    def force_finish(self) -> dict:
        """Operator override: mark the match complete now, computing a result
        line from the current score (best-effort), and lock it against
        auto-infer. Bumps the generation so the next poll sees POST_MATCH."""
        with self._lock:
            s = self._state
            res = compute_result(s, force=True)
            if res is not None:
                s.result, s.result_description = res
            elif not s.result:
                s.result, s.result_description = ("C", "Match complete")
            s.result_manual = True
            self._generation += 1
            return {
                "result": s.result,
                "result_description": s.result_description,
                "generation": self._generation,
            }

    def reopen(self) -> dict:
        """Operator override: clear any result and unlock auto-infer, returning
        the wall to the live scoreboard. Undoes a premature/incorrect finish."""
        with self._lock:
            s = self._state
            s.result = ""
            s.result_description = ""
            s.result_manual = False
            self._generation += 1
            return {"generation": self._generation}


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
    # Runs go forward only — the COV-derived path may have us at a higher
    # total already because BTS is sometimes a delivery behind.
    new_runs = max(inn.runs, runs)
    if inn.runs == new_runs and inn.wickets == wkts:
        return False
    inn.runs    = new_runs
    inn.wickets = wkts
    s.status    = "In Progress"
    return True


def _h_ovb(s: MatchState, value: str) -> bool:
    overs = _parse_overs(value)
    inn = _current_innings(s)
    # Overs go forward only (see BTS for the same rationale).
    if _legal_balls_from_overs(overs) <= _legal_balls_from_overs(inn.overs):
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
    """COV is the running ball-by-ball summary of the current over. It is
    refreshed on every delivery, including ones where BTS/OVB aren't sent.
    Treat it as the authoritative source for "where in the over we are" and
    derive runs/overs from it, never letting them go backwards.

    Detect end-of-over by ball-count shrinkage between successive COVs and
    bank the current totals into _legal_balls_at_over_start /
    _runs_at_over_start so the next over starts from a known baseline. On
    rollover the per-batter attribution cursor resets too.

    Each new ball's runs are credited to whichever bat[*] B*K marks as on
    strike — the app stops sending B*S after the connection-init snapshot,
    so this attribution is the only way to keep per-batter scores live.
    """
    inn = _current_innings(s)
    balls_meta = _parse_cov_balls_meta(value)
    balls_list = [r for r, _ in balls_meta]
    balls      = len(balls_meta)
    runs       = sum(balls_list)

    if balls < inn._prev_cov_balls and inn._prev_cov_balls > 0:
        inn._legal_balls_at_over_start += inn._prev_cov_balls
        inn._runs_at_over_start         = max(inn._runs_at_over_start, inn.runs)
        inn._cov_balls_attributed       = 0

    inn._prev_cov_balls = balls

    # Credit any not-yet-attributed balls to the current striker, and update
    # the per-ball event counters consumed by the scoreboard.
    striker_changed = False
    if balls > inn._cov_balls_attributed:
        for ball_runs, ball_is_wicket in balls_meta[inn._cov_balls_attributed:balls]:
            s.last_ball_id        += 1
            s.last_ball_runs       = ball_runs
            s.last_ball_is_wicket  = ball_is_wicket
            if ball_runs > 0:
                inn.bat[inn._striker_idx].runs += ball_runs
                striker_changed = True
        inn._cov_balls_attributed = balls

    total_legal_balls = inn._legal_balls_at_over_start + balls
    derived_overs     = f"{total_legal_balls // 6}.{total_legal_balls % 6}"
    derived_runs      = inn._runs_at_over_start + runs

    changed = False
    if total_legal_balls > _legal_balls_from_overs(inn.overs):
        inn.overs = derived_overs
        changed = True
    if derived_runs > inn.runs:
        inn.runs = derived_runs
        changed = True
    if changed or striker_changed:
        s.status = "In Progress"
    return changed or striker_changed


def _h_batter_name(idx: int, s: MatchState, value: str) -> bool:
    name = value.strip()
    if not name:
        return False
    inn = _current_innings(s)
    if inn.bat[idx].batsman_name == name:
        return False
    inn.bat[idx].batsman_name = name
    return True


def _h_bowler_info(s: MatchState, value: str) -> bool:
    # F1N / F1S — current bowler name / stats. Informational; not surfaced
    # on the wall yet, but we accept them so they stop being logged as
    # UNKNOWN.
    return False


def _assign_home_away(s: MatchState) -> bool:
    """Map the two real team names (which the app sends per innings as BTN =
    batting, FTN = fielding) onto the home/away slots.

    BLE never encodes home vs away — only batting vs fielding, which swap each
    innings. So we fix the mapping from innings 1: the side batting first and
    the side fielding first are the two match teams. Rule:
      1. If exactly one of them contains our hint -> that side is home.
      2. Otherwise fall back to: team batting first = home.
    Computed off innings 1 (with a current-innings fallback for a role not yet
    seen) so the innings-2 role swap never re-swaps the labels. Returns True if
    home/away changed.
    """
    first = s.innings[0]
    cur   = _current_innings(s)
    bat_first = first.team_batting_name or cur.team_batting_name
    # The "other" team is the side fielding first. If FTN never arrived, the
    # team batting in innings 2 is that same side, so fall back to it.
    other = first.team_fielding_name
    if not other and len(s.innings) > 1:
        other = s.innings[1].team_batting_name
    if not other:
        other = cur.team_fielding_name
    if not bat_first and not other:
        return False

    hint = (s._our_team_hint or "").casefold()
    home = away = ""
    if hint and bat_first and other:
        bat_match   = hint in bat_first.casefold()
        other_match = hint in other.casefold()
        if bat_match and not other_match:
            home, away = bat_first, other
        elif other_match and not bat_match:
            home, away = other, bat_first
    if not home and not away:
        # Positional fallback: team batting first is home.
        home, away = bat_first, other

    changed = False
    if home and s.home_team_name != home:
        s.home_team_name = home
        changed = True
    if away and s.away_team_name != away:
        s.away_team_name = away
        changed = True
    return changed


def _h_ftn(s: MatchState, value: str) -> bool:
    """FTN = fielding team name this innings (a real name from the app)."""
    name = value.strip()
    if not name:
        return False
    cur = _current_innings(s)
    changed = False
    if cur.team_fielding_name != name:
        cur.team_fielding_name = name
        changed = True
    changed |= _assign_home_away(s)
    return changed


def _h_btn(s: MatchState, value: str) -> bool:
    """BTN = batting team name this innings (a real name from the app). A BTN
    that differs from the current innings' batting team triggers the "open 2nd
    innings" path (the batting side flipped)."""
    name = value.strip()
    if not name:
        return False
    _ensure_second_innings(s, name)
    cur = _current_innings(s)
    changed = False
    if cur.team_batting_name != name:
        cur.team_batting_name = name
        changed = True
    changed |= _assign_home_away(s)
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
    """B1K1 / B2K1 — striker indicator. Update _striker_idx so the COV
    handler attributes subsequent balls to the right batter. Either '1'
    (this batter is now on strike) or '0' (the other batter is) is honoured.
    """
    inn = _current_innings(s)
    v = value.strip()
    if v == "1":
        new_idx = idx
    elif v == "0":
        new_idx = 1 - idx
    else:
        return False
    if inn._striker_idx == new_idx:
        return False
    inn._striker_idx = new_idx
    return True


def _h_lwk(s: MatchState, value: str) -> bool:
    try:
        team_score = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    # Last wicket: append/update a Fow entry for the most recent dismissal.
    if not inn.fow or inn.fow[-1].runs != team_score:
        inn.fow.append(Fow(runs=team_score, wickets=inn.wickets or len(inn.fow) + 1))
        s.last_wicket_id += 1
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
    "B1N": lambda s, v: _h_batter_name(0, s, v),
    "B2N": lambda s, v: _h_batter_name(1, s, v),
    "F1N": _h_bowler_info,
    "F1S": _h_bowler_info,
    "LWK": _h_lwk,
    "LWS": _h_lws,
    "LWD": _h_lwd,
}
