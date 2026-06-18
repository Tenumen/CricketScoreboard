"""Unit tests for match-over inference (compute_result) and the operator
force_finish / reopen overrides. The BLE feed sends no result token, so these
derive the winner from the 2nd-innings score."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playcricket_ble_bridge.state import (
    Innings,
    MatchState,
    MatchAccumulator,
    compute_result,
)
from playcricket_ble_bridge.serializers import match_detail_to_dict


def _two_innings(first_runs, chase_runs, chase_wkts, chase_overs,
                 no_of_overs=20, players_per_side=11,
                 team1="Aston on Trent", team2="Opponents",
                 revised_target=0):
    s = MatchState(no_of_overs=no_of_overs, players_per_side=players_per_side)
    s.innings = [
        Innings(innings_number=1, team_batting_name=team1, runs=first_runs,
                wickets=10, overs=f"{no_of_overs}.0"),
        Innings(innings_number=2, team_batting_name=team2, runs=chase_runs,
                wickets=chase_wkts, overs=chase_overs,
                revised_target_runs=revised_target),
    ]
    return s


# ---------- not decided -------------------------------------------------------

def test_single_innings_is_not_a_result():
    s = MatchState()
    assert compute_result(s) is None


def test_chase_in_progress_is_not_a_result():
    # 100/3 chasing 201 with overs left -> match not over.
    s = _two_innings(first_runs=200, chase_runs=100, chase_wkts=3, chase_overs="10.0")
    assert compute_result(s) is None


# ---------- chase succeeds ----------------------------------------------------

def test_win_by_wickets():
    s = _two_innings(first_runs=150, chase_runs=151, chase_wkts=4, chase_overs="18.2")
    assert compute_result(s) == ("W", "Opponents won by 6 wickets")


def test_win_by_one_wicket_is_singular():
    s = _two_innings(first_runs=150, chase_runs=151, chase_wkts=9, chase_overs="19.5")
    assert compute_result(s) == ("W", "Opponents won by 1 wicket")


def test_revised_target_used_for_chase():
    # DLS revised target of 120; chase reaches it.
    s = _two_innings(first_runs=200, chase_runs=120, chase_wkts=2, chase_overs="15.0",
                     revised_target=120)
    assert compute_result(s) == ("W", "Opponents won by 8 wickets")


# ---------- defending side wins ----------------------------------------------

def test_win_by_runs_all_out():
    s = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10, chase_overs="17.3")
    assert compute_result(s) == ("W", "Aston on Trent won by 20 runs")


def test_win_by_runs_overs_exhausted():
    s = _two_innings(first_runs=200, chase_runs=190, chase_wkts=5, chase_overs="20.0")
    assert compute_result(s) == ("W", "Aston on Trent won by 10 runs")


def test_win_by_one_run_is_singular():
    s = _two_innings(first_runs=200, chase_runs=199, chase_wkts=10, chase_overs="19.4")
    assert compute_result(s) == ("W", "Aston on Trent won by 1 run")


def test_tie():
    s = _two_innings(first_runs=160, chase_runs=160, chase_wkts=10, chase_overs="20.0")
    assert compute_result(s) == ("T", "Match tied")


# ---------- force / reopen overrides -----------------------------------------

def test_force_finish_on_undecided_match_locks_result():
    acc = MatchAccumulator(our_club_id=12345)
    s = acc.snapshot()  # snapshot returns the live state object
    s.innings = _two_innings(first_runs=200, chase_runs=120, chase_wkts=3,
                             chase_overs="10.0").innings
    out = acc.force_finish()
    # 120 chasing 201 -> defending side ahead by 80 at the freeze point.
    assert out["result"] == "W"
    assert out["result_description"] == "Aston on Trent won by 80 runs"
    assert acc.snapshot().result_manual is True


def test_force_finish_with_no_innings_falls_back():
    acc = MatchAccumulator()
    out = acc.force_finish()
    assert out["result"] == "C"
    assert out["result_description"] == "Match complete"


def test_reopen_clears_result_and_unlocks():
    acc = MatchAccumulator()
    acc.force_finish()
    acc.reopen()
    s = acc.snapshot()
    assert s.result == ""
    assert s.result_description == ""
    assert s.result_manual is False


def test_autoresult_is_sticky_until_reopen():
    # Once auto-inferred, a later in-progress-looking state must not clear it.
    acc = MatchAccumulator()
    s = acc.snapshot()
    s.innings = _two_innings(first_runs=150, chase_runs=151, chase_wkts=4,
                             chase_overs="18.2").innings
    acc._maybe_autoresult()
    assert acc.snapshot().result_description == "Opponents won by 6 wickets"
    # Mutate as if a stray correction arrived; sticky result stays.
    acc._maybe_autoresult()
    assert acc.snapshot().result_description == "Opponents won by 6 wickets"


# ---------- operator manual names reach the result line + innings JSON --------

def test_override_names_in_result_line_chase_win():
    """Manual names win over the app's batting names in the result line. Home
    bats first (innings 1), away chases and wins (innings 2)."""
    s = _two_innings(first_runs=150, chase_runs=151, chase_wkts=4, chase_overs="18.2",
                     team1="PC Home", team2="PC Away")
    s.home_team_name_override = "Aston 1st XI"
    s.away_team_name_override = "Repton CC"
    assert compute_result(s) == ("W", "Repton CC won by 6 wickets")


def test_override_names_in_result_line_defending_win():
    s = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10, chase_overs="17.3",
                     team1="PC Home", team2="PC Away")
    s.home_team_name_override = "Aston 1st XI"
    s.away_team_name_override = "Repton CC"
    assert compute_result(s) == ("W", "Aston 1st XI won by 20 runs")


def test_partial_override_leaves_other_side_as_app_name():
    # Only away overridden; a chase win must use the manual away name.
    s = _two_innings(first_runs=150, chase_runs=151, chase_wkts=4, chase_overs="18.2",
                     team1="PC Home", team2="PC Away")
    s.away_team_name_override = "Repton CC"
    assert compute_result(s) == ("W", "Repton CC won by 6 wickets")
    # Only home overridden; a defending win must use the manual home name.
    s2 = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10, chase_overs="17.3",
                      team1="PC Home", team2="PC Away")
    s2.home_team_name_override = "Aston 1st XI"
    assert compute_result(s2) == ("W", "Aston 1st XI won by 20 runs")


def test_override_names_in_serialized_innings_summaries():
    s = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10, chase_overs="17.3",
                     team1="PC Home", team2="PC Away")
    s.home_team_name_override = "Aston 1st XI"
    s.away_team_name_override = "Repton CC"
    d = match_detail_to_dict(s)
    assert d["innings"][0]["team_batting_name"] == "Aston 1st XI"   # innings 1 = home
    assert d["innings"][1]["team_batting_name"] == "Repton CC"      # innings 2 = away


def test_override_after_result_refreshes_description():
    """A name typed AFTER the match result was inferred refreshes the frozen
    result line (it is otherwise sticky)."""
    acc = MatchAccumulator()
    s = acc.snapshot()
    s.innings = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10,
                             chase_overs="17.3", team1="PC Home",
                             team2="PC Away").innings
    acc._maybe_autoresult()
    assert acc.snapshot().result_description == "PC Home won by 20 runs"
    acc.set_team_names(home="Aston 1st XI", away="Repton CC")
    assert acc.snapshot().result_description == "Aston 1st XI won by 20 runs"


def test_splash_names_distinct_when_innings2_opened_by_target():
    """Match-day bug: opponent unnamed (the app sends the literal 'Away') bats
    first, our side chases, and innings 2 is opened by a target (BTT) with no
    distinguishing BTN for our side. The post-match splash and result line must
    still show two distinct names -- anchored to the positional home/away
    resolution the Console uses -- not the away name twice."""
    acc = MatchAccumulator()
    # Innings 1: opponent (unnamed -> 'Away') bats and is bowled out for 120.
    acc.apply("BTN", "Away")
    acc.apply("FTN", "Aston on Trent")
    acc.apply("BTS", "120/10")
    # Innings break: the app sends the chase target but no fresh BTN.
    acc.apply("BTT", "121")
    # Our side knocks off the runs for the loss of 4 wickets.
    acc.apply("BTS", "121/4")
    s = acc.snapshot()

    d = match_detail_to_dict(s)
    first = d["innings"][0]["team_batting_name"]
    second = d["innings"][1]["team_batting_name"]
    assert first == "Away"                       # innings 1 = side batting first
    assert second == "Aston on Trent"            # innings 2 = our side (resolved)
    assert first != second                       # the bug was both == "Away"
    assert compute_result(s) == ("W", "Aston on Trent won by 6 wickets")


def test_serialized_innings_keep_app_name_without_override():
    s = _two_innings(first_runs=200, chase_runs=180, chase_wkts=10, chase_overs="17.3",
                     team1="PC Home", team2="PC Away")
    s.away_team_name_override = "Repton CC"     # only away overridden
    d = match_detail_to_dict(s)
    assert d["innings"][0]["team_batting_name"] == "PC Home"        # unchanged
    assert d["innings"][1]["team_batting_name"] == "Repton CC"
