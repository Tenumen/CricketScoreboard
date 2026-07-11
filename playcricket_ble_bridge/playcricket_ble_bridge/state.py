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


# A team slot whose name the app has not sent yet stays BLANK, not a "Team ?"
# placeholder: the wall shows only what Play-Cricket has actually sent, and the
# real name fills in the moment it arrives (see _assign_home_away).


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
    # Pairs cricket: the app sends BTS as a bare total (no "/wkts") and a wicket
    # is a -5 run penalty rather than a dismissal. Latched True the first time a
    # no-slash BTS arrives. BTS is ALWAYS the authoritative total now (set
    # directly, may rise or fall) — this flag no longer gates the score; it is
    # used only to suppress the innings-summary extras derivation, which is
    # meaningless in pairs (batter scores go negative on the -5 penalty).
    pairs: bool = False

    # Dismissed batters, in order of dismissal, for this innings. Each entry is
    # a Bat with batsman_name + final runs (+ balls/how_out where sent). Built
    # from the LWN/LWS/LWD tokens (the app sends the out-batter's name and score
    # on each wicket). Combined with the two not-out bat[] slots this gives the
    # full batting card the innings-summary screen needs (top-two scorers and
    # the extras derivation total − sum(all batters)). See _h_lwn.
    dismissed: List["Bat"] = field(default_factory=list)
    # Most-recent non-blank LWN value, so a re-sent dismissal (the app replays
    # the cluster) maps to the same dismissed entry rather than a duplicate.
    _last_lwn_name: str = ""
    # Set by _h_lwk: the just-reported fall score is BELOW the current total, so
    # this is a stale connection-snapshot replay of a pre-connect wicket, not a
    # live dismissal — _h_lwn skips adding it to the card.
    _stale_wicket: bool = False

    # COV is used ONLY to fire per-ball / per-wicket event splashes now — it no
    # longer derives runs or overs (BTS/OVB own those authoritatively, and COV
    # can't read extras: a 'wd'/'2nb' token would corrupt any derived figure).
    # These two cursors keep the event tap idempotent across polls and over
    # rollovers. See _h_cov.
    _prev_cov_balls:       int = 0
    _cov_balls_attributed: int = 0
    # Striker side per the last B*K token (0 = bat[0], 1 = bat[1]). Tracked for a
    # possible future on-strike marker; NOT used to attribute runs (B*S is the
    # authoritative per-batter source) and NOT drawn on the wall today.
    _striker_idx: int = 0


@dataclass
class InningsSummary:
    """Frozen snapshot of a completed innings, shown on the wall during the
    interval. Populated by MatchAccumulator.finish_innings() when the operator
    presses 'Innings finished' (the BLE feed sends no innings-over signal).
    `has_extras` is False in pairs cricket, where extras cannot be derived."""
    active: bool = False
    innings_number: int = 0
    team_batting_name: str = ""
    runs: int = 0
    wickets: int = 0
    overs: str = "0.0"
    has_extras: bool = False
    extras: int = 0
    bat1_name: str = ""
    bat1_runs: int = 0
    bat2_name: str = ""
    bat2_runs: int = 0


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
    # Operator forced the live scoreboard on even though no ball has been bowled
    # (0/0, no batters). Lets the wall leave the PRE_MATCH splash for the live
    # layout before Play-Cricket has sent any score. Sticky until the next reset.
    force_live: bool = False
    match_date: str = ""
    innings: List[Innings] = field(default_factory=lambda: [Innings(innings_number=1)])

    # Operator-typed name overrides from the admin console. When non-empty for a
    # side, they take precedence over whatever the app sent for that side (see
    # _assign_home_away); empty means "use the app's name / PENDING placeholder".
    # On MatchState so reset() (which rebuilds MatchState) clears them with the
    # rest of the game.
    home_team_name_override: str = ""
    away_team_name_override: str = ""

    # NOTE: home/away are mapped purely positionally from innings 1 (side batting
    # first = home, side fielding first = away). The team names always come
    # straight from the app's BTN/FTN tokens — no hint matching or club defaults —
    # unless the operator has typed a manual override.

    # Monotonic per-ball / per-wicket counters consumed by the C++ scoreboard
    # to trigger event splashes. Bumped from _h_cov / _h_lwk. The runs/wicket
    # flag describe only the most recent ball (or wicket); older balls are
    # not retained here.
    last_ball_id:        int  = 0
    last_ball_runs:      int  = 0
    last_ball_is_wicket: bool = False
    last_wicket_id:      int  = 0

    # Frozen innings-summary screen (operator 'Innings finished'). Sticky until
    # the next innings resumes play or an explicit clear (reset/blank/reopen).
    innings_summary: InningsSummary = field(default_factory=InningsSummary)
    # last_ball_id at the moment the summary was frozen; the summary auto-clears
    # once last_ball_id moves past this (a genuine ball = play has resumed).
    _summary_freeze_ball_id: int = 0


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


def _batting_card(inn: Innings) -> List[Bat]:
    """Every batter who has batted this innings: the dismissed batters (with
    their final runs) plus the not-out batters still at the crease, deduped by
    name (the dismissed record wins — it covers the window between a dismissal
    and the next B*N where the out batter still occupies a bat[] slot)."""
    out_names = {b.batsman_name for b in inn.dismissed if b.batsman_name}
    card: List[Bat] = [b for b in inn.dismissed if b.batsman_name]
    for b in inn.bat:
        if b.batsman_name and b.batsman_name not in out_names:
            card.append(b)
    return card


def _top_two(inn: Innings) -> List[Bat]:
    """The two highest scorers of the innings, runs descending."""
    return sorted(_batting_card(inn), key=lambda b: b.runs, reverse=True)[:2]


def _derived_extras(inn: Innings) -> Optional[int]:
    """Extras = team total − sum(all batters' runs). The BLE feed never sends
    extras, so we derive them; this is exact at innings end only in full cricket
    with a complete batting card. Returns None (i.e. "don't show extras") in
    pairs cricket — where a wicket is a −5 penalty and batter scores go negative,
    making the identity meaningless — and when the batters' sum exceeds the team
    total (attribution drift), where any figure would be wrong."""
    if inn.pairs:
        return None
    extras = inn.runs - sum(b.runs for b in _batting_card(inn))
    return extras if extras >= 0 else None


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
    # Prefer the positionally resolved names (home bats first, so innings 1's
    # batting side is home and innings 2's is away). home_team_name/away_team_name
    # are computed by _assign_home_away, already fold in any operator override,
    # and match what the Console shows -- so the result headline stays consistent
    # with the rest of the wall and never duplicates a name when the raw
    # per-innings team_batting_name is stale/copied. Fall back to the override
    # then the per-innings name for states built without _assign_home_away.
    team_first = (s.home_team_name or s.home_team_name_override
                  or inn1.team_batting_name or "Team 1")
    team_chase = (s.away_team_name or s.away_team_name_override
                  or inn2.team_batting_name or "Team 2")

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

    def __init__(self, our_club_id: int = 0):
        self._lock = RLock()
        self._state = MatchState()
        self._state.home_club_id = our_club_id
        # home/away team names are learned directly from the app's BTN/FTN
        # tokens and mapped positionally; nothing else about naming is configured.
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
                self._maybe_clear_summary()
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

    def _maybe_clear_summary(self) -> None:
        """Clear a frozen innings summary once play has resumed — i.e. a genuine
        ball has been bowled since the freeze (last_ball_id advanced). This is
        the only reliable 'next innings started' signal: innings-level runs/overs
        can jump from the BTT-before-BTN target synthesis or a snapshot replay,
        but last_ball_id only moves on a real COV-delivered ball. Holds the lock."""
        s = self._state
        if s.innings_summary.active and s.last_ball_id > s._summary_freeze_ball_id:
            s.innings_summary = InningsSummary()

    def finish_innings(self) -> dict:
        """Operator override: freeze a summary of the innings that just ended and
        show it on the wall through the interval. The BLE feed has no innings-over
        token, so this is a manual button. Captures runs/wickets/overs, the top
        two scorers, and derived extras (full cricket only — None in pairs), then
        bumps the generation so the next poll picks it up. Sticky until the next
        innings resumes play (_maybe_clear_summary) or an explicit clear."""
        with self._lock:
            s = self._state
            inn = _current_innings(s)
            top = _top_two(inn)
            extras = _derived_extras(inn)
            # Team name honouring the operator override (home bats first, so
            # innings 1 -> home override, innings 2 -> away), mirroring the
            # result-line and post-match logic.
            override = (s.home_team_name_override if inn.innings_number == 1
                        else s.away_team_name_override)
            team = override or inn.team_batting_name
            # Build a fresh InningsSummary from copied scalar values — never alias
            # the live bat/dismissed lists, so later apply() calls can't mutate
            # the frozen snapshot.
            summ = InningsSummary(
                active=True,
                innings_number=inn.innings_number,
                team_batting_name=team,
                runs=inn.runs,
                wickets=inn.wickets,
                overs=inn.overs,
                has_extras=extras is not None,
                extras=extras if extras is not None else 0,
                bat1_name=top[0].batsman_name if len(top) >= 1 else "",
                bat1_runs=top[0].runs        if len(top) >= 1 else 0,
                bat2_name=top[1].batsman_name if len(top) >= 2 else "",
                bat2_runs=top[1].runs        if len(top) >= 2 else 0,
            )
            s.innings_summary = summ
            s._summary_freeze_ball_id = s.last_ball_id
            self._generation += 1
            return {
                "generation":     self._generation,
                "innings_number": summ.innings_number,
                "runs":           summ.runs,
                "wickets":        summ.wickets,
                "extras":         summ.extras if summ.has_extras else None,
                "bat1":           [summ.bat1_name, summ.bat1_runs],
                "bat2":           [summ.bat2_name, summ.bat2_runs],
            }

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
            s.innings_summary = InningsSummary()  # back to the live board
            self._generation += 1
            return {"generation": self._generation}

    def reset(self) -> dict:
        """Operator override: wipe the match back to a clean slate so the wall
        returns to the idle logo (NO_MATCH) and is ready to accept a fresh
        game's data. Used both to clear a frozen board after a dropped BLE link
        and to abandon a test/custom match before starting a real one — the
        latter matters because score handlers are forward-only (BTS uses
        max()), so a new 0/0 would never overwrite a stale total without this.

        Preserves the configured home-club id (the only field __init__ seeds);
        everything else is discarded."""
        with self._lock:
            our_club_id = self._state.home_club_id
            self._state = MatchState()
            self._state.home_club_id = our_club_id
            self._generation += 1
            return {"generation": self._generation}

    def blank_scoreboard(self) -> dict:
        """Operator override: force the live scoreboard on now, even with no ball
        bowled (0/0, no batters). For a match that has started but before
        Play-Cricket has sent any score — moves the wall off the PRE_MATCH
        splash onto the live layout. Non-destructive: clears any result so it
        isn't treated as POST_MATCH, but leaves team/innings data intact so the
        board fills in live as tokens arrive. Sticky until reset()."""
        with self._lock:
            s = self._state
            s.force_live = True
            s.result = ""
            s.result_description = ""
            s.result_manual = False
            s.innings_summary = InningsSummary()  # manual dismiss of the summary
            self._generation += 1
            return {"generation": self._generation}

    def set_team_names(self, home: str = "", away: str = "") -> dict:
        """Operator override: pin the displayed home/away names. A non-empty name
        wins over whatever the app sends for that side; an empty string removes
        the override for that side, reverting to the app's name (or the PENDING
        placeholder until it arrives). Cleared wholesale by reset() (new game)."""
        with self._lock:
            s = self._state
            s.home_team_name_override = (home or "").strip()
            s.away_team_name_override = (away or "").strip()
            # Recompute the display names from app data + overrides. Clear first
            # so a *removed* override doesn't leave a stale name behind when the
            # app hasn't supplied one.
            s.home_team_name = ""
            s.away_team_name = ""
            _assign_home_away(s)
            # The result line is computed once at match-end and frozen. If a
            # result already exists, refresh it so a name typed after the match
            # finished appears in the "X won by N" headline too.
            if s.result:
                res = compute_result(s, force=True)
                if res is not None:
                    s.result, s.result_description = res
            self._generation += 1
            return {
                "generation": self._generation,
                "home_team_name": s.home_team_name,
                "away_team_name": s.away_team_name,
            }


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
    """BTS = the batting side's authoritative team total, 'runs/wkts' (full
    cricket) or a bare 'runs' (pairs, or a template that omits wickets).

    The app IS the source of truth: set runs directly, in BOTH directions, so a
    scorer's correction (e.g. 17 -> 15 after removing a mis-entered ball) takes
    effect on the very next refresh. No forward-only clamp — that clamp was the
    root cause of corrections never reaching the wall.

    Wickets are only touched when the value actually carries them (a '/'). A
    bare total carries NO wicket information, so it must NOT reset wickets to 0
    — doing so was the cause of the erratic/disappearing wickets whenever the
    app sent a bare BTS."""
    runs, wkts = _parse_score(value)
    inn = _current_innings(s)
    has_wkts = "/" in value
    # Latch pairs mode on a bare total (used only by the innings-summary extras
    # derivation — see Innings.pairs). It no longer affects the score path.
    if value.strip() and not has_wkts:
        inn.pairs = True
    changed = False
    if inn.runs != runs:
        inn.runs = runs
        changed = True
    if has_wkts and inn.wickets != wkts:
        inn.wickets = wkts
        changed = True
    if changed:
        s.status = "In Progress"
    return changed


def _h_ovb(s: MatchState, value: str) -> bool:
    """OVB = the authoritative over.ball count, extras-aware (the app has
    already excluded wides/no-balls from the legal-ball count). Set it directly,
    in both directions, so a corrected over count reaches the wall. No
    forward-only clamp and no COV-derived guess — OVB is the sole owner of the
    over count."""
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
    """COV is the ball-by-ball summary of the current over, refreshed every
    delivery. It is used ONLY to fire the per-ball / per-wicket event splashes
    — it never drives the score.

    Why not derive runs/overs from COV: the strip lists one token per delivery
    including wides/no-balls (a 'wd'/'2nb' token), so counting its length
    over-counts legal balls, and its per-token run parse can't read the extra's
    value. The team total (BTS), over.ball (OVB) and per-batter runs (B*S) all
    arrive authoritatively and set their own fields directly — deriving anything
    from COV only re-introduced drift and blocked corrections. So COV is now a
    pure event tap.

    End-of-over is detected by ball-count shrinkage between successive COVs,
    which resets the attribution cursor so the first ball of the new over emits
    a fresh event."""
    inn = _current_innings(s)
    balls_meta = _parse_cov_balls_meta(value)
    balls      = len(balls_meta)

    if balls < inn._prev_cov_balls and inn._prev_cov_balls > 0:
        inn._cov_balls_attributed = 0
    inn._prev_cov_balls = balls

    changed = False
    if balls > inn._cov_balls_attributed:
        for ball_runs, ball_is_wicket in balls_meta[inn._cov_balls_attributed:balls]:
            s.last_ball_id        += 1
            s.last_ball_runs       = ball_runs
            s.last_ball_is_wicket  = ball_is_wicket
            changed = True
        inn._cov_balls_attributed = balls
    if changed:
        s.status = "In Progress"
    return changed


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
    """Map the app's per-innings batting/fielding names onto the home/away slots.

    BLE never encodes home vs away — only batting vs fielding, which swap each
    innings. So we fix the mapping positionally from innings 1: the side batting
    first is home, the side fielding first is away. Computed off innings 1 (with
    a current-innings fallback for a role not yet seen) so the innings-2 role
    swap never re-swaps the labels. The displayed names always come straight
    from the app — no hint matching and no club default substitution.

    A side whose name has not arrived yet stays BLANK (not a "Team ?"
    placeholder): the wall shows only what the app has actually sent, and the
    real name fills in the moment it arrives. Returns True if home/away changed.
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

    # Operator-typed overrides win over the app-derived names, per side. Resolved
    # before the "nothing known" guard so a manual name can drive the display even
    # before any innings/BTN/FTN has arrived (pre-match naming).
    home = s.home_team_name_override or bat_first
    away = s.away_team_name_override or other
    if not home and not away:
        return False

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
    # may have sent BTT before BTN, in which case we open innings 2 now. Leave
    # the batting-team name EMPTY rather than copying innings 1's: copying it
    # left both innings carrying the same name (and the post-match splash
    # showing one team twice) whenever a distinguishing BTN never arrived. The
    # name is filled by the next BTN, and the displayed name is anchored to the
    # positional home/away resolution by the serializer regardless.
    cur = _current_innings(s)
    if cur.innings_number == 1:
        s.innings.append(Innings(innings_number=2, team_batting_name=""))
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
    """B1K / B2K — striker indicator ('1' = this batter on strike, '0' = the
    other). Recorded in _striker_idx for a possible future on-strike marker, but
    it drives nothing displayed today (per-batter runs come authoritatively from
    B*S), so it never reports a change — that would trigger a needless redraw."""
    inn = _current_innings(s)
    v = value.strip()
    if v == "1":
        inn._striker_idx = idx
    elif v == "0":
        inn._striker_idx = 1 - idx
    return False


def _h_lwk(s: MatchState, value: str) -> bool:
    try:
        team_score = int(value or 0)
    except ValueError:
        return False
    inn = _current_innings(s)
    # A fall-of-wicket score below the current total is a stale connection-
    # snapshot replay of a pre-connect wicket, not a live dismissal — flag it so
    # _h_lwn doesn't add a phantom batter to the card. (LWK leads the cluster, so
    # the flag is fresh when LWN arrives.)
    inn._stale_wicket = team_score < inn.runs
    # Last wicket: append/update a Fow entry for the most recent dismissal.
    if not inn.fow or inn.fow[-1].runs != team_score:
        inn.fow.append(Fow(runs=team_score, wickets=inn.wickets or len(inn.fow) + 1))
        s.last_wicket_id += 1
        return True
    return False


def _h_lwn(s: MatchState, value: str) -> bool:
    """LWN — dismissed batter's name. A non-blank value that differs from the
    previous one starts a new dismissed-batter entry (LWS/LWD then decorate it).
    The app re-sends the cluster (same name) and later blanks it; both are no-ops
    here. A stale connection-snapshot wicket (see _h_lwk) updates the name guard
    but is not added to the card."""
    name = value.strip()
    if not name or name == _current_innings(s)._last_lwn_name:
        return False
    inn = _current_innings(s)
    inn._last_lwn_name = name
    if inn._stale_wicket:
        return False
    inn.dismissed.append(Bat(position=len(inn.dismissed) + 1, batsman_name=name))
    return True


def _h_lws(s: MatchState, value: str) -> bool:
    """LWS — dismissed batter's score, 'runs (balls)' e.g. '60 (39)'. Attaches
    the final runs/balls to the current dismissed entry."""
    v = value.strip()
    inn = _current_innings(s)
    if not v or not inn.dismissed:
        return False
    runs_str = v.split("(", 1)[0].strip()
    try:
        runs = int(runs_str)
    except ValueError:
        return False
    balls = 0
    if "(" in v and ")" in v:
        try:
            balls = int(v[v.index("(") + 1:v.index(")")].strip())
        except ValueError:
            balls = 0
    last = inn.dismissed[-1]
    if last.runs == runs and last.balls == balls:
        return False
    last.runs = runs
    last.balls = balls
    return True


def _h_lwd(s: MatchState, value: str) -> bool:
    code = value.strip()
    name = T.DISMISSAL_NAMES.get(code, code)
    inn = _current_innings(s)
    changed = False
    if inn.fow and inn.fow[-1].how_out != name:
        inn.fow[-1].how_out = name
        changed = True
    # Decorate the current dismissed entry too, but never wipe it on the blank
    # re-send (name == "").
    if name and inn.dismissed and inn.dismissed[-1].how_out != name:
        inn.dismissed[-1].how_out = name
        changed = True
    return changed


def _h_noop(s: MatchState, value: str) -> bool:
    # LWB (incoming batter) / LWF (fielder): accepted so they stop logging as
    # UNKNOWN, but not surfaced on the wall.
    return False


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
    "LWN": _h_lwn,
    "LWS": _h_lws,
    "LWD": _h_lwd,
    "LWB": _h_noop,
    "LWF": _h_noop,
}
