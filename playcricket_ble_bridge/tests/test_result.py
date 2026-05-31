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
