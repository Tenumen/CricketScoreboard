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


def _innings_to_dict(inn: S.Innings) -> dict:
    return {
        "team_batting_name":  inn.team_batting_name,
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
        "no_of_players":         "11",
        "no_of_reserves":        "0",
        "result":                m.result,
        "result_description":    m.result_description,
        "result_applied_to":     "",
        "match_notes":           "",
        "points":                [],
        "match_result_types":    [],
        "players": [
            {"home_team": []},
            {"away_team": []},
        ],
        "innings": [_innings_to_dict(i) for i in m.innings],
        "last_event": {
            "ball_id":        m.last_ball_id,
            "ball_runs":      m.last_ball_runs,
            "ball_is_wicket": m.last_ball_is_wicket,
            "wicket_id":      m.last_wicket_id,
        },
    })
    return base


def result_summary_envelope(m: S.MatchState) -> dict:
    return {"result_summary": [match_summary_to_dict(m)]}


def match_detail_envelope(m: S.MatchState) -> dict:
    return {"match_details": [match_detail_to_dict(m)]}
