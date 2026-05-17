"""Serialize the internal dataclass tree to the Play-Cricket JSON shape.

Play-Cricket stringifies most numeric fields on the wire ("142", "22.4", "9"),
but keeps a few as raw numbers (match `id`, `no_of_overs`, `fow.wickets`). The
helpers below mirror that asymmetry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import state as S


def _s(v: Any) -> str:
    """Stringify a value the play-cricket way (empty for None)."""
    if v is None:
        return ""
    return str(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _bat_to_dict(b: S.Bat) -> dict:
    return {
        "position":     _s(b.position),
        "batsman_name": b.batsman_name,
        "batsman_id":   _s(b.batsman_id),
        "how_out":      b.how_out,
        "fielder_name": b.fielder_name,
        "fielder_id":   _s(b.fielder_id),
        "bowler_name":  b.bowler_name,
        "bowler_id":    _s(b.bowler_id),
        "runs":         _s(b.runs),
        "fours":        _s(b.fours),
        "sixes":        _s(b.sixes),
        "balls":        _s(b.balls),
    }


def _bowl_to_dict(b: S.Bowl) -> dict:
    overs = f"{b._legal_balls // 6}.{b._legal_balls % 6}"
    return {
        "bowler_name": b.bowler_name,
        "bowler_id":   _s(b.bowler_id),
        "overs":       overs,
        "maidens":     _s(b.maidens),
        "runs":        _s(b.runs),
        "wides":       _s(b.wides),
        "wickets":     _s(b.wickets),
        "no_balls":    _s(b.no_balls),
    }


def _fow_to_dict(f: S.Fow) -> dict:
    return {
        "runs":             _s(f.runs),
        "wickets":          f.wickets,                # number per real API
        "batsman_out_name": f.batsman_out_name,
        "batsman_out_id":   _s(f.batsman_out_id),
        "batsman_in_name":  f.batsman_in_name,
        "batsman_in_id":    _s(f.batsman_in_id),
        "batsman_in_runs":  _s(f.batsman_in_runs),
    }


def _innings_to_dict(inn: S.Innings) -> dict:
    return {
        "team_batting_name":  inn.team_batting_name,
        "team_batting_id":    _s(inn.team_batting_id),
        "innings_number":     inn.innings_number,
        "extra_byes":         _s(inn.extra_byes),
        "extra_leg_byes":     _s(inn.extra_leg_byes),
        "extra_wides":        _s(inn.extra_wides),
        "extra_no_balls":     _s(inn.extra_no_balls),
        "extra_penalty_runs": _s(inn.extra_penalty_runs),
        "penalties_runs_awarded_in_other_innings": _s(inn.penalties_runs_awarded_in_other_innings),
        "total_extras":       _s(inn.total_extras),
        "runs":               _s(inn.runs),
        "wickets":            _s(inn.wickets),
        "overs":              inn.overs,
        "declared":           inn.declared,
        "forfeited_innings":  inn.forfeited_innings,
        "revised_target_runs":  _s(inn.revised_target_runs),
        "revised_target_overs": inn.revised_target_overs,
        "bat":  [_bat_to_dict(b)  for b in inn.bat],
        "fow":  [_fow_to_dict(f)  for f in inn.fow],
        "bowl": [_bowl_to_dict(b) for b in inn.bowl],
    }


def _player_to_dict(p: S.Player) -> dict:
    return {
        "position":      p.position,
        "player_name":   p.player_name,
        "player_id":     p.player_id,
        "captain":       p.captain,
        "wicket_keeper": p.wicket_keeper,
    }


def match_summary_to_dict(m: S.MatchDetail) -> dict:
    """Subset used in matches.json and result_summary.json (no innings/players)."""
    return {
        "id":               m.id,
        "status":           m.status,
        "published":        m.published,
        "last_updated":     m.last_updated or _now_iso(),
        "league_name":      m.league_name,
        "league_id":        _s(m.league_id),
        "competition_name": m.competition_name,
        "competition_id":   _s(m.competition_id),
        "competition_type": m.competition_type,
        "match_type":       m.match_type,
        "game_type":        m.game_type,
        "season":           m.season,
        "match_date":       m.match_date,
        "match_time":       m.match_time,
        "ground_name":      m.ground_name,
        "ground_id":        _s(m.ground_id),
        "ground_latitude":  "",
        "ground_longitude": "",
        "home_club_name":   m.home_club_name,
        "home_team_name":   m.home_team_name,
        "home_team_id":     _s(m.home_team_id),
        "home_club_id":     _s(m.home_club_id),
        "away_club_name":   m.away_club_name,
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


def match_detail_to_dict(m: S.MatchDetail) -> dict:
    """Full match_detail.json shape — summary fields + match-level extras +
    players + innings."""
    base = match_summary_to_dict(m)
    base.update({
        "match_id":              _s(m.id),
        "toss_won_by_team_id":   _s(m.toss_won_by_team_id),
        "toss":                  m.toss,
        "batted_first":          m.batted_first,
        "no_of_overs":           m.no_of_overs,
        "no_of_innings":         _s(m.no_of_innings),
        "no_of_days":            _s(m.no_of_days),
        "no_of_players":         _s(m.no_of_players),
        "no_of_reserves":        _s(m.no_of_reserves),
        "result":                m.result,
        "result_description":    m.result_description,
        "result_applied_to":     m.result_applied_to,
        "match_notes":           m.match_notes,
        "points":                [],
        "match_result_types":    [],
        "players": [
            {"home_team": [_player_to_dict(p) for p in m.players_home]},
            {"away_team": [_player_to_dict(p) for p in m.players_away]},
        ],
        "innings": [_innings_to_dict(i) for i in m.innings],
    })
    return base
