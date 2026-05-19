"""Unit tests for the BLE token parser, accumulator, and serializer."""
from __future__ import annotations

import os
import sys

import pytest

# Make the package importable when running pytest from the project root or
# from inside tests/ without installation.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playcricket_ble_bridge import tokens as T
from playcricket_ble_bridge import serializers
from playcricket_ble_bridge.state import MatchAccumulator


# ---------- parse_frame -------------------------------------------------------

def test_parse_bytes():
    assert T.parse_frame(b"BTS245/3") == ("BTS", "245/3")


def test_parse_str():
    assert T.parse_frame("OVB32.3") == ("OVB", "32.3")


def test_parse_strips_crlf():
    assert T.parse_frame(b"B1K1\r\n") == ("B1K", "1")


def test_parse_short_payload_returns_none():
    assert T.parse_frame(b"AB") is None


def test_parse_empty():
    assert T.parse_frame(b"") is None
    assert T.parse_frame(None) is None


def test_parse_keeps_unknown_codes():
    code, value = T.parse_frame(b"XYZsomething")
    assert code == "XYZ"
    assert value == "something"
    assert not T.is_known(code)


def test_parse_text_with_spaces_in_team_name():
    # BTN values contain spaces; whitespace inside the value must be preserved.
    assert T.parse_frame(b"BTNAston on Trent 1st XI") == ("BTN", "Aston on Trent 1st XI")


# ---------- accumulator: individual handlers ----------------------------------

def test_bts_sets_runs_and_wickets():
    acc = MatchAccumulator()
    assert acc.apply("BTS", "245/3") is True
    snap = acc.snapshot()
    assert snap.innings[-1].runs == 245
    assert snap.innings[-1].wickets == 3
    assert acc.generation == 1


def test_bts_pairs_format_no_wickets():
    acc = MatchAccumulator()
    assert acc.apply("BTS", "12") is True
    snap = acc.snapshot()
    assert snap.innings[-1].runs == 12
    assert snap.innings[-1].wickets == 0


def test_bts_idempotent():
    acc = MatchAccumulator()
    acc.apply("BTS", "100/2")
    g1 = acc.generation
    # Re-apply the same value: no state change, no generation bump.
    assert acc.apply("BTS", "100/2") is False
    assert acc.generation == g1


def test_ovb_normalises_bare_integer():
    acc = MatchAccumulator()
    acc.apply("OVB", "5")
    assert acc.snapshot().innings[-1].overs == "5.0"
    acc.apply("OVB", "5.3")
    assert acc.snapshot().innings[-1].overs == "5.3"


def test_btn_sets_home_team_name_first_innings():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent"
    assert snap.innings[-1].team_batting_name == "Aston on Trent"


def test_btn_change_opens_second_innings():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "180/8")
    # Second innings: different batting team
    acc.apply("BTN", "Melbourne")
    snap = acc.snapshot()
    assert len(snap.innings) == 2
    assert snap.innings[0].team_batting_name == "Aston on Trent"
    assert snap.innings[0].runs == 180
    assert snap.innings[1].team_batting_name == "Melbourne"
    assert snap.innings[1].innings_number == 2


def test_btt_sets_revised_target_and_opens_second_innings():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "180/8")
    # Even without an explicit BTN swap, a target implies 2nd innings.
    acc.apply("BTT", "181")
    snap = acc.snapshot()
    assert len(snap.innings) == 2
    assert snap.innings[1].revised_target_runs == 181


def test_batter_score_independent_per_position():
    acc = MatchAccumulator()
    acc.apply("B1S", "67")
    acc.apply("B2S", "34")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[0].runs == 67
    assert inn.bat[1].runs == 34


def test_batter_balls():
    acc = MatchAccumulator()
    acc.apply("B1B", "42")
    assert acc.snapshot().innings[-1].bat[0].balls == 42


def test_unknown_code_recorded_but_does_not_change_state():
    acc = MatchAccumulator()
    assert acc.apply("ZZZ", "whatever") is False
    assert "ZZZ" in acc.unknown_codes()
    assert acc.unknown_codes()["ZZZ"] == 1


def test_lwk_creates_fow_entry():
    acc = MatchAccumulator()
    acc.apply("BTS", "100/3")
    acc.apply("LWK", "100")
    acc.apply("LWD", "lbw")
    snap = acc.snapshot()
    fow = snap.innings[-1].fow
    assert len(fow) == 1
    assert fow[0].runs == 100
    assert fow[0].how_out == "lbw"


# ---------- realistic scoring sequence ----------------------------------------

def test_realistic_scoring_sequence_produces_in_progress_match():
    acc = MatchAccumulator(our_club_id=42)
    # Innings 1 — Aston on Trent batting
    for code, val in [
        ("BTN", "Aston on Trent 1st XI"),
        ("FTN", "Melbourne 1st XI"),
        ("BTS", "0/0"),
        ("OVB", "0.0"),
        ("OVR", "40"),
        ("B1S", "0"), ("B1B", "0"), ("B1K", "1"),
        ("B2S", "0"), ("B2B", "0"), ("B2K", "0"),
        ("BTS", "245/3"),
        ("OVB", "32.3"),
        ("B1S", "67"), ("B1B", "82"),
        ("B2S", "34"), ("B2B", "41"),
    ]:
        acc.apply(code, val)

    snap = acc.snapshot()
    detail = serializers.match_detail_envelope(snap)
    md = detail["match_details"][0]
    assert md["home_team_name"] == "Aston on Trent 1st XI"
    assert md["away_team_name"] == "Melbourne 1st XI"
    assert md["status"] == "In Progress"
    inn = md["innings"][0]
    assert inn["runs"] == "245"
    assert inn["wickets"] == "3"
    assert inn["overs"] == "32.3"
    # At least the active batters appear in bat[].
    runs = sorted(int(b["runs"]) for b in inn["bat"])
    assert runs == [34, 67]


def test_result_summary_envelope_shape():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "10/0")
    env = serializers.result_summary_envelope(acc.snapshot())
    assert "result_summary" in env
    assert isinstance(env["result_summary"], list)
    assert env["result_summary"][0]["id"] == 9000001
    assert env["result_summary"][0]["home_team_name"] == "Aston on Trent"
