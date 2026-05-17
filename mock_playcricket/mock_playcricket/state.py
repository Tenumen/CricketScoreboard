"""Dataclass tree mirroring the Play-Cricket match_detail JSON shape.

Numbers are stored natively (int/bool); the serializer stringifies on output
to match Play-Cricket's wire format ("142", "22.4", etc.). Internal fields
(prefixed with `_`) are not serialized — they track engine state like the
striker position and legal-ball count.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Player:
    position: int
    player_name: str
    player_id: int
    captain: bool = False
    wicket_keeper: bool = False


@dataclass
class Bat:
    position: int
    batsman_name: str
    batsman_id: int
    how_out: str = ""           # "" / "not out" while at the crease
    fielder_name: str = ""
    fielder_id: str = ""
    bowler_name: str = ""
    bowler_id: str = ""
    runs: int = 0
    fours: int = 0
    sixes: int = 0
    balls: int = 0


@dataclass
class Bowl:
    bowler_name: str
    bowler_id: int
    maidens: int = 0
    runs: int = 0
    wides: int = 0
    wickets: int = 0
    no_balls: int = 0
    # internal
    _legal_balls: int = 0
    _runs_in_current_over: int = 0


@dataclass
class Fow:
    runs: int
    wickets: int
    batsman_out_name: str
    batsman_out_id: int
    batsman_in_name: str
    batsman_in_id: int
    batsman_in_runs: int = 0


@dataclass
class Innings:
    team_batting_name: str
    team_batting_id: int
    innings_number: int
    extra_byes: int = 0
    extra_leg_byes: int = 0
    extra_wides: int = 0
    extra_no_balls: int = 0
    extra_penalty_runs: int = 0
    penalties_runs_awarded_in_other_innings: int = 0
    declared: bool = False
    forfeited_innings: bool = False
    revised_target_runs: int = 0
    revised_target_overs: str = ""
    bat: List[Bat] = field(default_factory=list)
    bowl: List[Bowl] = field(default_factory=list)
    fow: List[Fow] = field(default_factory=list)

    # internal engine state (not serialized to play-cricket JSON)
    _legal_balls: int = 0
    _striker_pos: int = 1
    _non_striker_pos: int = 2
    _current_bowler_idx: int = 0
    _balls_this_over: int = 0
    _closed: bool = False

    # derived totals (recomputed by engine.recompute)
    runs: int = 0
    wickets: int = 0
    total_extras: int = 0

    @property
    def overs(self) -> str:
        return f"{self._legal_balls // 6}.{self._legal_balls % 6}"


@dataclass
class MatchDetail:
    id: int
    home_team_name: str
    away_team_name: str
    home_team_id: int = 0
    away_team_id: int = 0
    home_club_name: str = ""
    away_club_name: str = ""
    home_club_id: int = 0
    away_club_id: int = 0
    status: str = "New"
    published: str = "Yes"
    match_date: str = ""           # DD/MM/YYYY
    match_time: str = "13:00"
    ground_name: str = ""
    ground_id: int = 0
    league_name: str = ""
    league_id: int = 0
    competition_name: str = "Friendly"
    competition_id: int = 0
    competition_type: str = "Friendly"
    match_type: str = "Limited Overs"
    game_type: str = "Standard"
    season: str = ""
    no_of_overs: int = 20
    no_of_innings: int = 2
    no_of_days: int = 1
    no_of_players: int = 11
    no_of_reserves: int = 0
    toss: str = ""                 # team name that won
    toss_won_by_team_id: int = 0
    batted_first: str = ""         # team name that batted first
    result: str = ""
    result_description: str = ""
    result_applied_to: str = ""
    match_notes: str = ""
    last_updated: str = ""

    players_home: List[Player] = field(default_factory=list)
    players_away: List[Player] = field(default_factory=list)
    innings: List[Innings] = field(default_factory=list)


@dataclass
class MatchStore:
    matches: dict = field(default_factory=dict)   # id -> MatchDetail
    active_match_id: Optional[int] = None
    next_id: int = 9000001

    def active(self) -> Optional[MatchDetail]:
        if self.active_match_id is None:
            return None
        return self.matches.get(self.active_match_id)

    def allocate_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i
