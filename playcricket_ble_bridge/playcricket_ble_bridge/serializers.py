"""Render the accumulator's MatchState into the Play-Cricket JSON shapes the
scoreboard24 binary already polls (`result_summary.json` and
`match_detail.json`). Field names mirror mock_playcricket.serializers so the
C++ side is none the wiser.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import state as S


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _bat_to_dict(b: S.Bat) -> dict:
    return {
        "position":     _s(b.position),
        "batsman_name": b.batsman_name,
        "batsman_id":   "",
        "how_out":      b.how_out,
        "fielder_name": b.fielder_name,
        "fielder_id":   "",
        "bowler_name":  b.bowler_name,
        "bowler_id":    "",
        "runs":         _s(b.runs),
        "fours":        _s(b.fours),
        "sixes":        _s(b.sixes),
        "balls":        _s(b.balls),
    }


def _fow_to_dict(f: S.Fow) -> dict:
    return {
        "runs":             _s(f.runs),
        "wickets":          f.wickets,
        "batsman_out_name": f.batsman_out_name,
        "batsman_out_id":   "",
        "batsman_in_name":  "",
        "batsman_in_id":    "",
        "batsman_in_runs":  "",
    }


def _innings_summary_to_dict(sm: "S.InningsSummary") -> dict:
    """Frozen innings-summary screen (operator 'Innings finished'). `extras` is
    "" when not derivable (pairs cricket / attribution drift) so the wall omits
    the Extras line rather than showing a misleading 0."""
    return {
        "active":             sm.active,
        "innings_number":     sm.innings_number,
        "team_batting_name":  sm.team_batting_name,
        "runs":               _s(sm.runs),
        "wickets":            _s(sm.wickets),
        "overs":              sm.overs,
        "extras":             _s(sm.extras) if sm.has_extras else "",
        "bat": [
            {"batsman_name": sm.bat1_name, "runs": _s(sm.bat1_runs)},
            {"batsman_name": sm.bat2_name, "runs": _s(sm.bat2_runs)},
        ],
    }


def _innings_to_dict(inn: S.Innings) -> dict:
    return {
        "team_batting_name":  inn.team_batting_name,
        "team_fielding_name": inn.team_fielding_name,
        "team_batting_id":    "",
        "innings_number":     inn.innings_number,
        "extra_byes":         "0",
        "extra_leg_byes":     "0",
        "extra_wides":        "0",
        "extra_no_balls":     "0",
        "extra_penalty_runs": "0",
        "penalties_runs_awarded_in_other_innings": "0",
        "total_extras":       "0",
        "runs":               _s(inn.runs),
        "wickets":            _s(inn.wickets),
        "overs":              inn.overs,
        "declared":           False,
        "forfeited_innings":  False,
        "revised_target_runs":  _s(inn.revised_target_runs) if inn.revised_target_runs else "0",
        "revised_target_overs": "",
        "bat":  [_bat_to_dict(b) for b in inn.bat if b.batsman_name or b.runs or b.balls or b.how_out],
        "fow":  [_fow_to_dict(f) for f in inn.fow],
        "bowl": [],
    }


def match_summary_to_dict(m: S.MatchState) -> dict:
    """Used by result_summary.json — no innings/players."""
    return {
        "id":               m.id,
        "status":           m.status,
        "published":        "Yes",
        "last_updated":     _now_iso(),
        "league_name":      "",
        "league_id":        "",
        "competition_name": "BLE Bridge",
        "competition_id":   "",
        "competition_type": "Friendly",
        "match_type":       "Limited Overs",
        "game_type":        "Standard",
        "season":           str(datetime.now().year),
        "match_date":       m.match_date,
        "match_time":       "13:00",
        "ground_name":      "",
        "ground_id":        "",
        "ground_latitude":  "",
        "ground_longitude": "",
        "home_club_name":   m.home_team_name,
        "home_team_name":   m.home_team_name,
        "home_team_id":     _s(m.home_team_id),
        "home_club_id":     _s(m.home_club_id),
        "away_club_name":   m.away_team_name,
        "away_team_name":   m.away_team_name,
        "away_team_id":     _s(m.away_team_id),
        "away_club_id":     _s(m.away_club_id),
        "umpire_1_name": "", "umpire_1_id": "",
        "umpire_2_name": "", "umpire_2_id": "",
        "umpire_3_name": "", "umpire_3_id": "",
        "referee_name":  "", "referee_id":  "",
        "scorer_1_name": "", "scorer_1_id": "",
        "scorer_2_name": "", "scorer_2_id": "",
    }


def match_detail_to_dict(m: S.MatchState) -> dict:
    base = match_summary_to_dict(m)
    base.update({
        "match_id":              _s(m.id),
        "toss_won_by_team_id":   "",
        "toss":                  "",
        "batted_first":          "",
        "no_of_overs":           m.no_of_overs,
        "no_of_innings":         "2",
        "no_of_days":            "1",
        "no_of_players":         _s(m.players_per_side),
        "no_of_reserves":        "0",
        "result":                m.result,
        "result_description":    m.result_description,
        "result_applied_to":     "",
        "force_live":            m.force_live,
        "match_notes":           "",
        "points":                [],
        "match_result_types":    [],
        "players": [
            {"home_team": []},
            {"away_team": []},
        ],
        "innings": [_innings_to_dict(i) for i in m.innings],
        "innings_summary": _innings_summary_to_dict(m.innings_summary),
        "last_event": {
            "ball_id":        m.last_ball_id,
            "ball_runs":      m.last_ball_runs,
            "ball_is_wicket": m.last_ball_is_wicket,
            "wicket_id":      m.last_wicket_id,
        },
    })
    # Resolve each innings' displayed batting AND fielding names so the wall
    # (which reads the current innings' two sides directly) always shows the
    # right pair. Precedence, per the "show what the app sent" mandate:
    #   1. operator override  (pins a physical team; follows it across innings)
    #   2. the raw per-innings BTN/FTN the app actually sent this innings
    #   3. positional fill    (only when the app hasn't sent that role yet)
    # The two teams swap roles each innings. `home` = batted first, `away` =
    # fielded first, so:
    #   innings 1 -> batting = home,  fielding = away
    #   innings 2 -> batting = away,  fielding = home
    # (2) beats (3) deliberately: if the app sends FTN='Aston' in innings 2, that
    # explicit value must win over a positional guess derived from a stale/wrong
    # innings-1 name. (3) still supplies a fielding name for the common case
    # where the app doesn't re-send FTN in the 2nd innings.
    home_fill = m.home_team_name or m.home_team_name_override
    away_fill = m.away_team_name or m.away_team_name_override
    _bat_fill   = {1: home_fill, 2: away_fill}
    _field_fill = {1: away_fill, 2: home_fill}
    home_ov = m.home_team_name_override
    away_ov = m.away_team_name_override
    _bat_ov   = {1: home_ov, 2: away_ov}
    _field_ov = {1: away_ov, 2: home_ov}
    for inn_dict, inn in zip(base["innings"], m.innings):
        num = inn.innings_number
        if _bat_ov.get(num):
            inn_dict["team_batting_name"] = _bat_ov[num]
        elif not inn_dict["team_batting_name"] and _bat_fill.get(num):
            inn_dict["team_batting_name"] = _bat_fill[num]
        if _field_ov.get(num):
            inn_dict["team_fielding_name"] = _field_ov[num]
        elif not inn_dict["team_fielding_name"] and _field_fill.get(num):
            inn_dict["team_fielding_name"] = _field_fill[num]
    return base


def result_summary_envelope(m: S.MatchState) -> dict:
    return {"result_summary": [match_summary_to_dict(m)]}


def match_detail_envelope(m: S.MatchState) -> dict:
    return {"match_details": [match_detail_to_dict(m)]}
