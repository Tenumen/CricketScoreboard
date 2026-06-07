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


def test_home_away_empty_at_construction():
    """No team name is hardcoded — both slots are empty until the app's
    BTN/FTN tokens arrive."""
    snap = MatchAccumulator().snapshot()
    assert snap.home_team_name == ""
    assert snap.away_team_name == ""


def test_real_match_hint_maps_our_side_home_even_when_fielding():
    """The exact 2026-05-31 scenario: our club fielded first. Both real names
    come from the app; the 'Aston' hint puts our side in the home slot."""
    acc = MatchAccumulator()                       # default hint = "Aston"
    acc.apply("BTN", "Sutton Bonington CC Sunday XI")   # opposition batting
    acc.apply("FTN", "Aston on Trent Village CC 1st XI") # we are fielding
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent Village CC 1st XI"
    assert snap.away_team_name == "Sutton Bonington CC Sunday XI"
    assert snap.innings[0].team_batting_name  == "Sutton Bonington CC Sunday XI"
    assert snap.innings[0].team_fielding_name == "Aston on Trent Village CC 1st XI"


def test_hint_maps_our_side_home_when_batting():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")             # we bat first
    acc.apply("FTN", "Melbourne 1st XI")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent"
    assert snap.away_team_name == "Melbourne 1st XI"


def test_positional_fallback_when_no_hint_match():
    """Neither name contains the hint -> team batting first is home."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Repton CC")                  # batting first
    acc.apply("FTN", "Melbourne 1st XI")           # fielding first
    snap = acc.snapshot()
    assert snap.home_team_name == "Repton CC"
    assert snap.away_team_name == "Melbourne 1st XI"


def test_home_away_stable_across_innings_flip():
    """Once set from innings 1, the home/away labels do not re-swap when the
    batting side flips for innings 2."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Sutton Bonington CC Sunday XI")
    acc.apply("FTN", "Aston on Trent Village CC 1st XI")
    acc.apply("BTS", "180/8")
    acc.apply("BTN", "Aston on Trent Village CC 1st XI")  # 2nd innings, we bat
    snap = acc.snapshot()
    assert len(snap.innings) == 2
    assert snap.home_team_name == "Aston on Trent Village CC 1st XI"
    assert snap.away_team_name == "Sutton Bonington CC Sunday XI"
    assert snap.innings[1].team_batting_name == "Aston on Trent Village CC 1st XI"


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
        ("BTN", "Aston on Trent"),                 # our side bats -> home via hint
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


def test_bts_pairs_total_may_fall_on_wicket():
    """Pairs cricket: a wicket is a -5 run penalty, so the bare-numeric BTS
    total can legitimately decrease — it must not be clamped upward."""
    acc = MatchAccumulator()
    assert acc.apply("BTS", "224") is True
    assert acc.apply("BTS", "219") is True          # wicket: 224 - 5
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 219
    assert inn.pairs is True


def test_pairs_cov_does_not_reinflate_total_past_penalty():
    """In pairs the COV strip can't see the -5 penalty (a 'W' ball is 0 runs),
    so once BTS has docked the runs the COV path must not push the total back
    up to the pre-wicket figure."""
    acc = MatchAccumulator()
    acc.apply("BTS", "224")                          # latch pairs mode
    acc.apply("COV", ". 1 1 1 1 W ")                 # 4 runs + a wicket this over
    acc.apply("BTS", "219")                          # app's net total after -5
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 219


def test_bts_full_format_still_clamps_runs_forward():
    """Regression guard: full-format BTS (with /wkts) keeps the forward-only
    behaviour, so a stale lower value never pulls the total back."""
    acc = MatchAccumulator()
    acc.apply("BTS", "224/3")
    assert acc.apply("BTS", "219/3") is False        # clamped: no change
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 224
    assert inn.pairs is False


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


# ---------- per-ball event counters (consumed by scoreboard splashes) --------

def test_last_ball_id_increments_per_ball():
    acc = MatchAccumulator()
    acc.apply("COV", "1 ")
    assert acc.snapshot().last_ball_id == 1
    assert acc.snapshot().last_ball_runs == 1
    assert acc.snapshot().last_ball_is_wicket is False

    acc.apply("COV", "1 4 ")
    assert acc.snapshot().last_ball_id == 2
    assert acc.snapshot().last_ball_runs == 4

    acc.apply("COV", "1 4 6 ")
    assert acc.snapshot().last_ball_id == 3
    assert acc.snapshot().last_ball_runs == 6


def test_last_ball_flags_wicket_on_cov_w():
    acc = MatchAccumulator()
    acc.apply("COV", "1 W ")
    snap = acc.snapshot()
    assert snap.last_ball_id == 2
    assert snap.last_ball_runs == 0
    assert snap.last_ball_is_wicket is True


def test_last_ball_id_survives_over_rollover():
    acc = MatchAccumulator()
    acc.apply("COV", "1 1 1 1 1 1 ")     # six balls — finish over
    acc.apply("COV", "4 ")                # new over starts
    snap = acc.snapshot()
    assert snap.last_ball_id == 7
    assert snap.last_ball_runs == 4


def test_last_wicket_id_increments_on_lwk():
    acc = MatchAccumulator()
    acc.apply("BTS", "10/1")
    acc.apply("LWK", "10")
    assert acc.snapshot().last_wicket_id == 1
    acc.apply("BTS", "25/2")
    acc.apply("LWK", "25")
    assert acc.snapshot().last_wicket_id == 2


def test_match_detail_envelope_carries_last_event():
    acc = MatchAccumulator()
    acc.apply("COV", "4 ")
    acc.apply("LWK", "4")
    env = serializers.match_detail_envelope(acc.snapshot())
    le = env["match_details"][0]["last_event"]
    assert le == {
        "ball_id":        1,
        "ball_runs":      4,
        "ball_is_wicket": False,
        "wicket_id":      1,
    }
