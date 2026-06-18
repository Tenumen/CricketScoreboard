"""Tests for the operator 'Innings finished' summary: dismissed-batter capture
(LWN/LWS), the full-innings batting card, top-two scorers, derived extras (full
cricket only — never in pairs), the finish_innings() freeze, auto-clear on the
next ball, and serialization of the innings_summary block."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playcricket_ble_bridge import tokens as T
from playcricket_ble_bridge.serializers import match_detail_to_dict
from playcricket_ble_bridge.state import MatchAccumulator, _batting_card, _top_two


def _dismiss(acc, fall_score, name, runs, balls, how="b"):
    """Apply one dismissal cluster as the app sends it: LWK (fall score) then
    LWN (out batter), LWS ('runs (balls)'), LWD (how out). Caller should set BTS
    to the fall score first so the live total matches (else it reads as stale)."""
    acc.apply("LWK", str(fall_score))
    acc.apply("LWN", name)
    acc.apply("LWS", f"{runs} ({balls})")
    acc.apply("LWD", how)


def _full_innings(acc):
    """A complete full-cricket innings: 200/3, three batters out (50/40/30),
    two not out (60/10). Card sum = 190 -> 10 extras."""
    acc.apply("BTN", "Aston on Trent")
    acc.apply("FTN", "Melbourne")
    acc.apply("BTS", "60/1");  _dismiss(acc, 60,  "A Adams", 50, 40)
    acc.apply("BTS", "150/2"); _dismiss(acc, 150, "B Brown", 40, 55, how="c")
    acc.apply("BTS", "190/3"); _dismiss(acc, 190, "C Clark", 30, 20, how="lbw")
    acc.apply("BTS", "200/3")
    acc.apply("B1N", "D Davis"); acc.apply("B1S", "60")
    acc.apply("B2N", "E Evans"); acc.apply("B2S", "10")


# ---------- token catalogue ---------------------------------------------------

def test_lw_tokens_now_known():
    for code in ("LWN", "LWB", "LWF"):
        assert T.is_known(code)


def test_stumped_decodes():
    assert T.DISMISSAL_NAMES["st"] == "stumped"


# ---------- dismissed-batter capture ------------------------------------------

def test_lwn_lws_capture_dismissed_batter():
    acc = MatchAccumulator()
    acc.apply("BTS", "60/1")
    _dismiss(acc, 60, "A Adams", 50, 40)
    inn = acc.snapshot().innings[-1]
    assert len(inn.dismissed) == 1
    assert inn.dismissed[0].batsman_name == "A Adams"
    assert inn.dismissed[0].runs == 50
    assert inn.dismissed[0].balls == 40
    assert inn.dismissed[0].how_out == "bowled"


def test_blank_and_duplicate_lwn_are_ignored():
    acc = MatchAccumulator()
    acc.apply("BTS", "60/1")
    _dismiss(acc, 60, "A Adams", 50, 40)
    # App replays the same cluster, then blanks it.
    assert acc.apply("LWN", "A Adams") is False     # same name -> no new entry
    assert acc.apply("LWN", " ") is False           # blank re-send -> ignored
    assert len(acc.snapshot().innings[-1].dismissed) == 1


def test_two_wickets_at_same_score_are_distinct():
    acc = MatchAccumulator()
    acc.apply("BTS", "60/2")
    _dismiss(acc, 60, "A Adams", 50, 40)
    _dismiss(acc, 60, "B Brown", 0, 1, how="ro")   # run out, same fall score
    names = [b.batsman_name for b in acc.snapshot().innings[-1].dismissed]
    assert names == ["A Adams", "B Brown"]


def test_stale_snapshot_replay_not_added_to_card():
    # On connect the app dumps the current total then replays the LAST wicket
    # (a lower fall score). That stale cluster must not become a card entry.
    acc = MatchAccumulator()
    acc.apply("BTS", "200/4")
    _dismiss(acc, 130, "A Adams", 60, 39)   # fall score 130 < total 200 -> stale
    assert acc.snapshot().innings[-1].dismissed == []


# ---------- batting card & top two --------------------------------------------

def test_batting_card_and_top_two():
    acc = MatchAccumulator()
    _full_innings(acc)
    inn = acc.snapshot().innings[-1]
    card = {b.batsman_name: b.runs for b in _batting_card(inn)}
    assert card == {"A Adams": 50, "B Brown": 40, "C Clark": 30,
                    "D Davis": 60, "E Evans": 10}
    top = _top_two(inn)
    assert [(b.batsman_name, b.runs) for b in top] == [("D Davis", 60), ("A Adams", 50)]


def test_card_dedupes_out_batter_still_in_bat_slot():
    # Between a dismissal and the next B*N the out batter still occupies bat[];
    # the dismissed record must win, not double-count.
    acc = MatchAccumulator()
    acc.apply("BTS", "60/1")
    acc.apply("B1N", "A Adams"); acc.apply("B1S", "50")
    _dismiss(acc, 60, "A Adams", 50, 40)   # same name now both out and in bat[0]
    inn = acc.snapshot().innings[-1]
    names = [b.batsman_name for b in _batting_card(inn)]
    assert names.count("A Adams") == 1


# ---------- derived extras ----------------------------------------------------

def test_extras_derived_full_cricket():
    acc = MatchAccumulator()
    _full_innings(acc)
    out = acc.finish_innings()
    assert out["runs"] == 200
    assert out["extras"] == 10            # 200 - (50+40+30+60+10)


def test_extras_suppressed_in_pairs():
    acc = MatchAccumulator()
    acc.apply("BTN", "Softball A")
    acc.apply("BTS", "150")               # bare number -> pairs latched
    acc.apply("B1N", "P One"); acc.apply("B1S", "40")
    acc.apply("B2N", "P Two"); acc.apply("B2S", "30")
    out = acc.finish_innings()
    assert out["extras"] is None
    assert acc.snapshot().innings_summary.has_extras is False


def test_extras_suppressed_on_attribution_drift():
    # If batters' runs exceed the team total (drift), show no extras.
    acc = MatchAccumulator()
    acc.apply("BTS", "100/0")
    acc.apply("B1N", "X"); acc.apply("B1S", "80")
    acc.apply("B2N", "Y"); acc.apply("B2S", "40")   # 120 > 100
    out = acc.finish_innings()
    assert out["extras"] is None


# ---------- finish_innings freeze, isolation, clear ---------------------------

def test_finish_innings_snapshot_fields():
    acc = MatchAccumulator()
    _full_innings(acc)
    g_before = acc.generation
    out = acc.finish_innings()
    sm = acc.snapshot().innings_summary
    assert sm.active and sm.innings_number == 1
    assert sm.team_batting_name == "Aston on Trent"
    assert (sm.runs, sm.wickets, sm.overs) == (200, 3, "0.0")
    assert (sm.bat1_name, sm.bat1_runs) == ("D Davis", 60)
    assert (sm.bat2_name, sm.bat2_runs) == ("A Adams", 50)
    assert acc.generation == g_before + 1
    assert out["generation"] == acc.generation


def test_frozen_summary_is_isolated_from_later_updates():
    acc = MatchAccumulator()
    _full_innings(acc)
    acc.finish_innings()
    # A non-ball update (B1S) must not mutate the frozen snapshot.
    acc.apply("B1S", "999")
    sm = acc.snapshot().innings_summary
    assert sm.active and sm.bat1_runs == 60


def test_summary_auto_clears_when_play_resumes():
    acc = MatchAccumulator()
    _full_innings(acc)
    acc.finish_innings()
    assert acc.snapshot().innings_summary.active
    acc.apply("COV", "1")                 # a genuine ball -> last_ball_id advances
    assert acc.snapshot().innings_summary.active is False


def test_summary_cleared_by_blank_reopen_reset():
    for clear in ("blank_scoreboard", "reopen", "reset"):
        acc = MatchAccumulator()
        _full_innings(acc)
        acc.finish_innings()
        assert acc.snapshot().innings_summary.active
        getattr(acc, clear)()
        assert acc.snapshot().innings_summary.active is False


# ---------- serialization -----------------------------------------------------

def test_serializer_emits_summary_block():
    acc = MatchAccumulator()
    _full_innings(acc)
    acc.finish_innings()
    blk = match_detail_to_dict(acc.snapshot())["innings_summary"]
    assert blk["active"] is True
    assert blk["runs"] == "200" and blk["wickets"] == "3"
    assert blk["extras"] == "10"
    assert blk["bat"][0] == {"batsman_name": "D Davis", "runs": "60"}
    assert blk["bat"][1] == {"batsman_name": "A Adams", "runs": "50"}


def test_serializer_summary_inactive_by_default():
    acc = MatchAccumulator()
    _full_innings(acc)
    blk = match_detail_to_dict(acc.snapshot())["innings_summary"]
    assert blk["active"] is False


def test_serializer_pairs_extras_blank():
    acc = MatchAccumulator()
    acc.apply("BTN", "Softball A")
    acc.apply("BTS", "150")
    acc.finish_innings()
    blk = match_detail_to_dict(acc.snapshot())["innings_summary"]
    assert blk["extras"] == ""
