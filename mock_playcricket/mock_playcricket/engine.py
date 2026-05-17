"""Scoring engine. Applies one delivery at a time to an Innings, maintaining
all the invariants the Play-Cricket JSON shape expects (team total = bat + extras,
wickets count, overs string, bowler attribution, striker rotation, FOW).

Public surface: apply_ball() and helpers for starting/ending an innings.
"""
from __future__ import annotations

from typing import Optional

from . import state as S


DELIVERY_KINDS = {"legal", "wide", "no_ball", "bye", "leg_bye", "wicket"}
BOWLER_CREDIT = {"Bowled", "Caught", "LBW", "Stumped", "Hit wicket"}


# ---------- helpers ----------

def _find_bat(innings: S.Innings, position: int) -> Optional[S.Bat]:
    for b in innings.bat:
        if b.position == position:
            return b
    return None


def _current_bowler(innings: S.Innings) -> S.Bowl:
    return innings.bowl[innings._current_bowler_idx]


def _max_bat_position(innings: S.Innings) -> int:
    return max((b.position for b in innings.bat), default=0)


def _is_out(b: S.Bat) -> bool:
    return b.how_out not in ("", "not out", "Not out")


def _swap_strike(innings: S.Innings) -> None:
    innings._striker_pos, innings._non_striker_pos = (
        innings._non_striker_pos, innings._striker_pos)


def recompute_derived(innings: S.Innings) -> None:
    """Recompute innings.runs, .wickets, .total_extras and per-bowler .runs after
    mutations. Cheaper than tracking each field on every event."""
    bat_runs = sum(b.runs for b in innings.bat)
    extras = (innings.extra_byes + innings.extra_leg_byes
              + innings.extra_wides + innings.extra_no_balls
              + innings.extra_penalty_runs)
    innings.total_extras = extras
    innings.runs = bat_runs + extras
    innings.wickets = sum(1 for b in innings.bat if _is_out(b))


# ---------- innings lifecycle ----------

def start_innings(match: S.MatchDetail, innings_number: int,
                  team_batting_name: str, team_batting_id: int,
                  openers: list[S.Player], opening_bowler: S.Player) -> S.Innings:
    if any(i.innings_number == innings_number for i in match.innings):
        raise ValueError(f"Innings {innings_number} already exists")
    if len(openers) != 2:
        raise ValueError("Need exactly two openers")
    inn = S.Innings(
        team_batting_name=team_batting_name,
        team_batting_id=team_batting_id,
        innings_number=innings_number,
    )
    for pos, pl in enumerate(openers, start=1):
        inn.bat.append(S.Bat(
            position=pos,
            batsman_name=pl.player_name,
            batsman_id=pl.player_id,
            how_out="not out",
        ))
    inn.bowl.append(S.Bowl(
        bowler_name=opening_bowler.player_name,
        bowler_id=opening_bowler.player_id,
    ))
    inn._striker_pos = 1
    inn._non_striker_pos = 2
    inn._current_bowler_idx = 0
    inn._balls_this_over = 0
    inn._legal_balls = 0
    inn._closed = False
    recompute_derived(inn)
    return inn


def close_innings(innings: S.Innings, declared: bool = False,
                  forfeited: bool = False) -> None:
    innings.declared = declared
    innings.forfeited_innings = forfeited
    innings._closed = True


def change_bowler(innings: S.Innings, new_bowler: S.Player) -> None:
    """Begin a new over with `new_bowler`. Appends a fresh Bowl row if this
    bowler hasn't bowled yet, otherwise points at their existing row."""
    for i, b in enumerate(innings.bowl):
        if b.bowler_id == new_bowler.player_id:
            innings._current_bowler_idx = i
            b._runs_in_current_over = 0
            return
    innings.bowl.append(S.Bowl(
        bowler_name=new_bowler.player_name,
        bowler_id=new_bowler.player_id,
    ))
    innings._current_bowler_idx = len(innings.bowl) - 1


# ---------- the main entry point ----------

def apply_ball(innings: S.Innings, match: S.MatchDetail, kind: str,
               runs: int = 0, dismissal: Optional[dict] = None) -> None:
    """Apply one delivery to the innings.

    kind:
      legal     — legal delivery, `runs` go off-the-bat to the striker
      wide      — wide; total extras = 1 + `runs` (overthrows etc), no legal ball
      no_ball   — no-ball; 1 penalty extra + `runs` go to striker, no legal ball
      bye       — legal ball, `runs` byes
      leg_bye   — legal ball, `runs` leg-byes
      wicket    — legal ball, wicket falls; `runs` off the bat (typically 0)

    dismissal (only for kind='wicket'):
      {how_out: str, fielder_name?: str, fielder_id?: int,
       new_batsman_name: str, new_batsman_id: int,
       out_pos?: int  (defaults to striker)}
    """
    if kind not in DELIVERY_KINDS:
        raise ValueError(f"Unknown delivery kind: {kind!r}")
    if innings._closed:
        raise ValueError("Innings is closed")
    if runs < 0:
        raise ValueError("Negative runs not allowed")

    striker = _find_bat(innings, innings._striker_pos)
    non_striker = _find_bat(innings, innings._non_striker_pos)
    if striker is None or non_striker is None:
        raise ValueError("Striker or non-striker not set on innings")
    bowler = _current_bowler(innings)

    is_legal_ball = True
    bowler_conceded = 0
    physical_runs_run = 0  # used for strike rotation on extras

    if kind == "legal":
        striker.runs += runs
        striker.balls += 1
        if runs == 4: striker.fours += 1
        if runs == 6: striker.sixes += 1
        bowler_conceded = runs
        physical_runs_run = runs

    elif kind == "bye":
        innings.extra_byes += runs
        striker.balls += 1
        # byes do not go on the bowler's analysis
        physical_runs_run = runs

    elif kind == "leg_bye":
        innings.extra_leg_byes += runs
        striker.balls += 1
        physical_runs_run = runs

    elif kind == "wide":
        # 1 wide-penalty + any additional physical runs (also recorded as wides)
        innings.extra_wides += 1 + runs
        bowler_conceded = 1 + runs
        bowler.wides += 1
        is_legal_ball = False
        physical_runs_run = runs   # wide penalty doesn't physically swap ends

    elif kind == "no_ball":
        # 1 no-ball penalty extra + any bat runs to the striker
        innings.extra_no_balls += 1
        bowler_conceded = 1 + runs  # penalty + bat runs both go on bowler
        bowler.no_balls += 1
        striker.runs += runs
        if runs == 4: striker.fours += 1
        if runs == 6: striker.sixes += 1
        # striker.balls NOT incremented on a no-ball (faced an illegal delivery)
        is_legal_ball = False
        physical_runs_run = runs

    elif kind == "wicket":
        if dismissal is None:
            raise ValueError("dismissal is required for kind='wicket'")
        striker.runs += runs
        striker.balls += 1
        bowler_conceded = runs
        physical_runs_run = runs

        out_pos = dismissal.get("out_pos", innings._striker_pos)
        outgoing = _find_bat(innings, out_pos)
        if outgoing is None or _is_out(outgoing):
            raise ValueError("Outgoing batter not at the crease")
        how = dismissal.get("how_out", "Bowled")
        outgoing.how_out = how
        outgoing.bowler_name = bowler.bowler_name
        outgoing.bowler_id = str(bowler.bowler_id)
        if "fielder_name" in dismissal:
            outgoing.fielder_name = dismissal["fielder_name"]
        if "fielder_id" in dismissal:
            outgoing.fielder_id = str(dismissal["fielder_id"])

        if how in BOWLER_CREDIT:
            bowler.wickets += 1

        # FOW entry
        # Apply the run accounting first so totals are correct in the FOW row
        recompute_derived(innings)

        # New batter at the next position
        new_pos = _max_bat_position(innings) + 1
        new_bat = S.Bat(
            position=new_pos,
            batsman_name=dismissal["new_batsman_name"],
            batsman_id=dismissal["new_batsman_id"],
            how_out="not out",
        )
        innings.bat.append(new_bat)
        innings.fow.append(S.Fow(
            runs=innings.runs,
            wickets=innings.wickets,
            batsman_out_name=outgoing.batsman_name,
            batsman_out_id=outgoing.batsman_id,
            batsman_in_name=new_bat.batsman_name,
            batsman_in_id=new_bat.batsman_id,
            batsman_in_runs=0,
        ))
        # Replace the outgoing position in striker/non-striker tracking
        if out_pos == innings._striker_pos:
            innings._striker_pos = new_pos
        else:
            innings._non_striker_pos = new_pos
        # If the batters crossed before the wicket fell, the swap is handled by
        # the odd-run check at the bottom of the function.

    bowler.runs += bowler_conceded
    bowler._runs_in_current_over += bowler_conceded

    if is_legal_ball:
        innings._legal_balls += 1
        innings._balls_this_over += 1
        bowler._legal_balls += 1

    # Strike rotation: odd physical runs swap, but only AFTER the wicket update
    # (so the new batter ends up where they should).
    if physical_runs_run % 2 == 1:
        _swap_strike(innings)

    # End of over: swap strike, increment maidens, advance bowler index — but
    # the new bowler must be set explicitly by the caller (change_bowler).
    if is_legal_ball and innings._balls_this_over == 6:
        if bowler._runs_in_current_over == 0:
            bowler.maidens += 1
        bowler._runs_in_current_over = 0
        innings._balls_this_over = 0
        _swap_strike(innings)

    # Auto-close on all-out or overs exhausted
    not_out_count = sum(1 for b in innings.bat if not _is_out(b))
    if not_out_count <= 1:
        innings._closed = True
    if innings._legal_balls >= match.no_of_overs * 6:
        innings._closed = True

    recompute_derived(innings)


def edit_innings(innings: S.Innings, patch: dict) -> None:
    """Direct-edit mode: overwrite selected fields and recompute.

    Accepted top-level keys: extras (b, lb, w, nb, pen), declared, forfeited_innings,
    revised_target_runs, revised_target_overs, bat (list of overrides keyed by position),
    bowl (list keyed by bowler_id), fow (replaced wholesale).
    Engine state (_striker_pos, _non_striker_pos, _current_bowler_idx, _legal_balls)
    can be set via "_legal_balls", "_striker_pos", "_non_striker_pos",
    "_current_bowler_idx", "_balls_this_over".
    """
    if "extras" in patch:
        ex = patch["extras"]
        if "b"   in ex: innings.extra_byes        = int(ex["b"])
        if "lb"  in ex: innings.extra_leg_byes    = int(ex["lb"])
        if "w"   in ex: innings.extra_wides       = int(ex["w"])
        if "nb"  in ex: innings.extra_no_balls    = int(ex["nb"])
        if "pen" in ex: innings.extra_penalty_runs = int(ex["pen"])
    if "declared" in patch: innings.declared = bool(patch["declared"])
    if "forfeited_innings" in patch: innings.forfeited_innings = bool(patch["forfeited_innings"])
    if "revised_target_runs" in patch: innings.revised_target_runs = int(patch["revised_target_runs"])
    if "revised_target_overs" in patch: innings.revised_target_overs = str(patch["revised_target_overs"])

    if "bat" in patch:
        by_pos = {b.position: b for b in innings.bat}
        for entry in patch["bat"]:
            pos = int(entry["position"])
            if pos not in by_pos:
                continue
            b = by_pos[pos]
            for f in ("batsman_name", "batsman_id", "how_out", "fielder_name",
                      "fielder_id", "bowler_name", "bowler_id",
                      "runs", "fours", "sixes", "balls"):
                if f in entry:
                    setattr(b, f, type(getattr(b, f))(entry[f]))

    if "bowl" in patch:
        by_id = {b.bowler_id: b for b in innings.bowl}
        for entry in patch["bowl"]:
            bid = int(entry["bowler_id"])
            if bid not in by_id:
                continue
            bo = by_id[bid]
            for f in ("bowler_name", "maidens", "runs", "wides", "wickets",
                      "no_balls", "_legal_balls"):
                if f in entry:
                    setattr(bo, f, type(getattr(bo, f))(entry[f]))

    for k in ("_striker_pos", "_non_striker_pos", "_current_bowler_idx",
              "_legal_balls", "_balls_this_over"):
        if k in patch:
            setattr(innings, k, int(patch[k]))

    if "fow" in patch:
        innings.fow = [S.Fow(**row) for row in patch["fow"]]

    recompute_derived(innings)
