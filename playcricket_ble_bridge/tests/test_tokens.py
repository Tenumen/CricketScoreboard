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


def test_home_team_name_hardcoded_at_construction():
    """home_team_name is pinned at MatchAccumulator init — the Play-Cricket
    Scorer app does not transmit it over BLE."""
    snap = MatchAccumulator().snapshot()
    assert snap.home_team_name == "Aston on Trent"


def test_btn_home_does_not_overwrite_hardcoded_home():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")             # home batting
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent"
    assert snap.innings[-1].team_batting_name == "Aston on Trent"
    assert snap.away_team_name == ""               # no away info yet


def test_btn_away_learns_away_team_name():
    acc = MatchAccumulator()
    acc.apply("BTN", "Melbourne")                  # away batting first
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent" # untouched
    assert snap.away_team_name == "Melbourne"
    assert snap.innings[-1].team_batting_name == "Melbourne"


def test_ftn_fills_away_team_name():
    acc = MatchAccumulator()
    acc.apply("FTN", "Away")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent"
    assert snap.away_team_name == "Away"


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
    assert snap.away_team_name == "Melbourne"


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
        ("BTN", "Aston on Trent"),                 # matches hardcoded home
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
    assert md["home_team_name"] == "Aston on Trent"
    assert md["away_team_name"] == "Melbourne 1st XI"
    assert md["status"] == "In Progress"
    inn = md["innings"][0]
    assert inn["runs"] == "245"
    assert inn["wickets"] == "3"
    assert inn["overs"] == "32.3"
    # At least the active batters appear in bat[].
    runs = sorted(int(b["runs"]) for b in inn["bat"])
    assert runs == [34, 67]


def test_cov_drives_runs_and_overs_when_bts_lags():
    """Scenario from real Pixel 9a output 2026-05-19: app sends COV every
    ball but BTS / OVB only on some balls. The wall must reflect the latest
    over count and runs via COV."""
    acc = MatchAccumulator()
    # Ball 1 dot, balls 2-5 singles, ball 6 single. App sends BTS only after
    # ball 5 ('4/0') and never after ball 6. The wall must still read 5/1.0.
    for code, val in [
        ("COV", ". "),                # ball 1: dot
        ("COV", ". 1 "),               # ball 2: 1 run
        ("COV", ". 1 1 "),             # ball 3
        ("COV", ". 1 1 1 "),           # ball 4
        ("OVB", "0.5"),                # explicit only after ball 5
        ("BTS", "4/0"),
        ("COV", ". 1 1 1 1 "),         # ball 5 (BTS / OVB already arrived)
        ("COV", ". 1 1 1 1 1 "),       # ball 6 — no BTS / OVB follow-up
    ]:
        acc.apply(code, val)
    inn = acc.snapshot().innings[-1]
    assert inn.runs  == 5,   f"expected 5 runs, got {inn.runs}"
    assert inn.overs == "1.0", f"expected 1.0 overs, got {inn.overs!r}"


def test_cov_rolls_over_at_end_of_over():
    acc = MatchAccumulator()
    # Complete one over of 6 singles, then a fresh over with one dot.
    for v in [". ", ". 1 ", ". 1 1 ", ". 1 1 1 ", ". 1 1 1 1 ", ". 1 1 1 1 1 "]:
        acc.apply("COV", v)
    acc.apply("COV", " ")                  # over rollover: empty COV
    acc.apply("COV", ". ")                 # ball 1 of over 2: dot
    inn = acc.snapshot().innings[-1]
    assert inn.runs  == 5
    assert inn.overs == "1.1"


def test_bts_does_not_regress_runs_when_arriving_stale():
    """COV-derived runs may exceed the most recent BTS; a stale BTS must not
    pull the total back down."""
    acc = MatchAccumulator()
    acc.apply("COV", ". 1 1 1 1 1 ")       # COV-derives 5 runs
    acc.apply("BTS", "4/0")                # stale BTS for ball 5; must not regress
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 5


def test_b1n_b2n_set_batsman_names():
    acc = MatchAccumulator()
    acc.apply("B1N", "A Afirstname")
    acc.apply("B2N", "B B")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[0].batsman_name == "A Afirstname"
    assert inn.bat[1].batsman_name == "B B"


def test_f1n_f1s_recognised_no_longer_unknown():
    acc = MatchAccumulator()
    acc.apply("F1N", "T T")
    acc.apply("F1S", "5/0 (1.0)")
    assert "F1N" not in acc.unknown_codes()
    assert "F1S" not in acc.unknown_codes()


def test_cov_credits_runs_to_current_striker():
    """Real-world Pixel 9a behaviour 2026-05-19: app emits B1S/B2S only at
    the connection-init snapshot. After that, per-batter runs must be
    derived from COV + B*K strike-tracking."""
    acc = MatchAccumulator()
    # Reconnect snapshot: COV shows first ball of over was a six, B1S says
    # B1 already has 9 (the snapshot includes prior overs), B2 has 2.
    acc.apply("COV", "6 ")
    acc.apply("B1S", "9")
    acc.apply("B1K", "1")
    acc.apply("B2S", "2")
    acc.apply("B2K", "0")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[0].runs == 9 and inn.bat[1].runs == 2

    # Ball 2 of the over: 2 runs by B1 (still on strike).
    acc.apply("COV", "6 2 ")
    assert acc.snapshot().innings[-1].bat[0].runs == 11

    # Ball 3: single, strike rotates to B2.
    acc.apply("COV", "6 2 1 ")
    acc.apply("B1K", "0")
    acc.apply("B2K", "1")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[0].runs == 12   # 11 + 1 (last ball B1 faced)
    assert inn._striker_idx == 1

    # Balls 4-6: three doubles by B2, no strike rotations.
    acc.apply("COV", "6 2 1 2 ")
    acc.apply("COV", "6 2 1 2 2 ")
    acc.apply("COV", "6 2 1 2 2 2 ")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[1].runs == 8    # 2 + 6
    assert inn.bat[0].runs == 12   # unchanged across over
    assert inn.runs == 15
    assert inn.overs == "1.0"


def test_b2s_snapshot_overrides_prior_cov_attribution():
    """A late B*S snapshot (e.g. after a reconnect mid-over) should replace
    whatever the COV path had derived."""
    acc = MatchAccumulator()
    acc.apply("COV", "6 ")       # COV credits 6 to default striker (B1)
    acc.apply("B1S", "9")        # snapshot says actually 9
    assert acc.snapshot().innings[-1].bat[0].runs == 9


def test_result_summary_envelope_shape():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "10/0")
    env = serializers.result_summary_envelope(acc.snapshot())
    assert "result_summary" in env
    assert isinstance(env["result_summary"], list)
    assert env["result_summary"][0]["id"] == 9000001
    assert env["result_summary"][0]["home_team_name"] == "Aston on Trent"
