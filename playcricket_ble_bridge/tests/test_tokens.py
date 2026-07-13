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


def test_positional_home_is_team_batting_first():
    """Home/away are mapped purely positionally: the side batting first is home,
    the side fielding first is away. Names come straight from the app — no hint
    matching, no club default."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Repton CC")                  # batting first
    acc.apply("FTN", "Melbourne 1st XI")           # fielding first
    snap = acc.snapshot()
    assert snap.home_team_name == "Repton CC"
    assert snap.away_team_name == "Melbourne 1st XI"


def test_positional_when_our_side_fields_first():
    """Our club fielded first: the batting-first opponent is home and we are
    away. Nothing promotes our side to home — both names are reported exactly
    as the app sent them."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Sutton Bonington CC Sunday XI")   # opposition batting
    acc.apply("FTN", "Aston on Trent Village CC 1st XI") # we are fielding
    snap = acc.snapshot()
    assert snap.home_team_name == "Sutton Bonington CC Sunday XI"
    assert snap.away_team_name == "Aston on Trent Village CC 1st XI"
    assert snap.innings[0].team_batting_name  == "Sutton Bonington CC Sunday XI"
    assert snap.innings[0].team_fielding_name == "Aston on Trent Village CC 1st XI"


def test_only_fielding_name_leaves_home_blank():
    """Only the fielding name arrived (the batting-team name hasn't been sent
    yet, e.g. it wasn't re-pushed after a reconnect). The not-yet-known home slot
    stays BLANK — the wall shows only what the app has actually sent, never a
    "Team ?" placeholder."""
    acc = MatchAccumulator()
    acc.apply("FTN", "Away Test")                  # only the fielding name
    snap = acc.snapshot()
    assert snap.home_team_name == ""
    assert snap.away_team_name == "Away Test"


def test_only_batting_name_leaves_away_blank():
    """Mirror case: only the batting name arrived, so the away slot stays blank."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Melbourne 1st XI")           # only the batting name
    snap = acc.snapshot()
    assert snap.home_team_name == "Melbourne 1st XI"
    assert snap.away_team_name == ""


def test_real_name_fills_blank_slot():
    """The blank slot fills the moment the missing app-sent name arrives."""
    acc = MatchAccumulator()
    acc.apply("FTN", "Away Test")                  # home still blank
    assert acc.snapshot().home_team_name == ""
    acc.apply("BTN", "Aston on Trent Village CC")  # batting-team name turns up
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston on Trent Village CC"
    assert snap.away_team_name == "Away Test"


def test_home_away_stable_across_innings_flip():
    """Once set from innings 1, the home/away labels do not re-swap when the
    batting side flips for innings 2."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Sutton Bonington CC Sunday XI")
    acc.apply("FTN", "Aston on Trent Village CC 1st XI")
    acc.apply("BTS", "180/8")
    acc.apply("BTN", "Aston on Trent Village CC 1st XI")  # 2nd innings batting flips
    snap = acc.snapshot()
    assert len(snap.innings) == 2
    assert snap.home_team_name == "Sutton Bonington CC Sunday XI"
    assert snap.away_team_name == "Aston on Trent Village CC 1st XI"
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


def test_dismissal_cluster_creates_fow_entry():
    # The fow entry is keyed on LWN (the app omits LWK when the fall score is
    # unchanged); LWK supplies the score, LWD the dismissal.
    acc = MatchAccumulator()
    acc.apply("BTS", "100/3")
    acc.apply("LWK", "100")
    acc.apply("LWN", "A Adams")
    acc.apply("LWD", "lbw")
    snap = acc.snapshot()
    fow = snap.innings[-1].fow
    assert len(fow) == 1
    assert fow[0].runs == 100
    assert fow[0].batsman_out_name == "A Adams"
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


def test_cov_never_drives_runs_or_overs():
    """Core mandate: the wall shows what the app sends. COV (the ball-by-ball
    strip) drives NEITHER the runs NOR the over count -- BTS owns runs, OVB owns
    overs. Here the last BTS is 4/0 and the last OVB is 0.5, so despite the COV
    strip listing five scoring tokens the totals read exactly the app's last
    authoritative values, and the two trailing COVs with no BTS/OVB change
    nothing."""
    acc = MatchAccumulator()
    for code, val in [
        ("COV", ". "),                # ball 1: dot
        ("COV", ". 1 "),               # ball 2: 1 run
        ("COV", ". 1 1 "),             # ball 3
        ("COV", ". 1 1 1 "),           # ball 4
        ("OVB", "0.5"),                # explicit over.ball
        ("BTS", "4/0"),                # authoritative total
        ("COV", ". 1 1 1 1 "),         # ball 5 — COV only, no BTS/OVB
        ("COV", ". 1 1 1 1 1 "),       # ball 6 — COV only, no BTS/OVB
    ]:
        acc.apply(code, val)
    inn = acc.snapshot().innings[-1]
    assert inn.runs  == 4,   f"expected BTS-owned 4 runs, got {inn.runs}"
    assert inn.overs == "0.5", f"expected OVB-owned 0.5 overs, got {inn.overs!r}"


def test_cov_alone_leaves_score_untouched():
    """With no BTS/OVB at all, COV is a pure event tap: the score stays 0/0.0
    however many balls the strip lists."""
    acc = MatchAccumulator()
    for v in [". ", ". 1 ", ". 1 1 ", ". 1 1 1 ", ". 1 1 1 1 ", ". 1 1 1 1 1 "]:
        acc.apply("COV", v)
    acc.apply("COV", " ")                  # over rollover: empty COV
    acc.apply("COV", ". ")                 # ball 1 of over 2: dot
    inn = acc.snapshot().innings[-1]
    assert inn.runs  == 0
    assert inn.overs == "0.0"
    # ...but the per-ball event counter DID advance (splashes still fire).
    assert acc.snapshot().last_ball_id > 0


def test_extra_does_not_advance_over_count():
    """Match-day bug (Problem 2): a wide/no-ball is an extra COV delivery but NOT
    a legal ball, so the over must not advance for it. The over count follows the
    app's extras-aware OVB, and COV -- which lists one token per delivery
    including the wide -- can never push it forward. Runs come from BTS."""
    acc = MatchAccumulator()
    # Over so far: legal, legal, WIDE, legal, legal -> 5 COV tokens but only 4
    # legal balls. The wide shows as an extra scoring token in the strip.
    acc.apply("COV", "1 ")
    acc.apply("COV", "1 1 ")
    acc.apply("COV", "1 1 wd ")
    acc.apply("COV", "1 1 wd 1 ")
    acc.apply("COV", "1 1 wd 1 1 ")
    acc.apply("OVB", "0.4")               # extras-aware: only 4 legal balls
    acc.apply("BTS", "5/0")               # authoritative total incl. the wide
    inn = acc.snapshot().innings[-1]
    assert inn.overs == "0.4"             # OVB-owned, never a COV-derived 0.5
    assert inn.runs  == 5                 # BTS-owned


def test_bts_correction_lowers_runs_immediately():
    """Problem 3: when the scorer corrects a mistake, the app re-sends BTS with a
    LOWER value on the next refresh. It must take effect at once -- the old
    forward-only max() clamp that ignored it was the root cause of corrections
    never reaching the wall. Real data: 24 June, BTS 17/1 -> 15/1."""
    acc = MatchAccumulator()
    acc.apply("BTS", "17/1")
    assert acc.snapshot().innings[-1].runs == 17
    assert acc.apply("BTS", "15/1") is True     # correction applied, not clamped
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 15
    assert inn.wickets == 1


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


def test_bts_full_format_applies_correction_downward():
    """Full-format BTS (with /wkts) is authoritative in BOTH directions: a lower
    corrected value overwrites the higher one. (Formerly this asserted the
    forward-only clamp -- the very bug behind Problem 3 -- now inverted.)"""
    acc = MatchAccumulator()
    acc.apply("BTS", "224/3")
    assert acc.apply("BTS", "219/3") is True         # correction applied
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 219
    assert inn.pairs is False


def test_bare_bts_does_not_reset_wickets():
    """Problem 5: a bare BTS (no '/wkts') carries no wicket information, so it
    must leave the wicket count alone -- never reset it to 0. The log had 173
    bare BTS values; the old code zeroed wickets on each, causing the erratic /
    disappearing wickets."""
    acc = MatchAccumulator()
    acc.apply("BTS", "48/2")                 # 2 down
    assert acc.snapshot().innings[-1].wickets == 2
    acc.apply("BTS", "49")                   # bare total -> runs update only
    inn = acc.snapshot().innings[-1]
    assert inn.runs == 49
    assert inn.wickets == 2                   # unchanged, NOT reset to 0
    acc.apply("BTS", "55/3")                  # next full BTS updates wickets
    assert acc.snapshot().innings[-1].wickets == 3


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


def test_cov_never_touches_batter_runs():
    """Per-batter runs are authoritative from B1S/B2S (the app sends them live,
    every ball -- confirmed in the 24 June log). COV must NOT add to them: doing
    both let the two paths fight and corrupt the scores. Here COV lists a six and
    a two but the batter runs stay exactly what B*S set, and a later B*S
    correction (downward) is honoured."""
    acc = MatchAccumulator()
    acc.apply("B1S", "9")
    acc.apply("B2S", "2")
    acc.apply("COV", "6 ")       # COV must not credit anyone
    acc.apply("COV", "6 2 ")
    inn = acc.snapshot().innings[-1]
    assert inn.bat[0].runs == 9      # unchanged by COV
    assert inn.bat[1].runs == 2

    acc.apply("B1S", "8")            # scorer correction, downward
    assert acc.snapshot().innings[-1].bat[0].runs == 8


def test_batter_strike_token_causes_no_redraw():
    """B*K is accepted (recorded for a possible future on-strike marker) but is
    not drawn today, so it must not report a change -- otherwise every strike
    swap would trigger a needless wall redraw."""
    acc = MatchAccumulator()
    assert acc.apply("B1K", "1") is False
    assert acc.apply("B2K", "1") is False


def test_result_summary_envelope_shape():
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "10/0")
    env = serializers.result_summary_envelope(acc.snapshot())
    assert "result_summary" in env
    assert isinstance(env["result_summary"], list)
    assert env["result_summary"][0]["id"] == 9000001
    assert env["result_summary"][0]["home_team_name"] == "Aston on Trent"


# ---------- role-based team names (Problem 4) --------------------------------

def test_serializer_emits_both_batting_and_fielding_names():
    """Each innings dict carries BOTH the batting and fielding team names, so the
    wall can show the current innings' two sides directly (role-based)."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Etwall CC Hawks")
    acc.apply("FTN", "Aston on Trent 1st XI")
    acc.apply("BTS", "40/2")
    detail = serializers.match_detail_to_dict(acc.snapshot())
    inn1 = detail["innings"][0]
    assert inn1["team_batting_name"]  == "Etwall CC Hawks"
    assert inn1["team_fielding_name"] == "Aston on Trent 1st XI"


def test_serializer_roles_swap_second_innings():
    """The two teams swap batting/fielding roles at the innings break; the
    serializer reflects that so the wall always names the side that is batting
    now on top."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Etwall CC Hawks")            # innings 1: Etwall bat
    acc.apply("FTN", "Aston on Trent 1st XI")      # Aston field
    acc.apply("BTS", "120/8")
    acc.apply("BTN", "Aston on Trent 1st XI")      # innings 2: Aston chase
    detail = serializers.match_detail_to_dict(acc.snapshot())
    inn2 = detail["innings"][1]
    assert inn2["team_batting_name"]  == "Aston on Trent 1st XI"
    assert inn2["team_fielding_name"] == "Etwall CC Hawks"


def test_override_follows_physical_team_across_innings():
    """An operator name override pins a PHYSICAL team, so it must follow that team
    when the roles swap: the side that batted first (home) fields in innings 2."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Etwall CC Hawks")            # home = batted first
    acc.apply("FTN", "Aston Wrong Name")           # away = fielded first
    acc.apply("BTS", "120/8")
    acc.apply("BTN", "Aston Wrong Name")           # innings 2 batting
    acc.set_team_names(home="Etwall CC Hawks", away="Aston on Trent 1st XI")
    detail = serializers.match_detail_to_dict(acc.snapshot())
    inn1, inn2 = detail["innings"][0], detail["innings"][1]
    # Innings 1: Etwall bat, Aston field.
    assert inn1["team_batting_name"]  == "Etwall CC Hawks"
    assert inn1["team_fielding_name"] == "Aston on Trent 1st XI"
    # Innings 2: Aston bat (override followed them), Etwall field.
    assert inn2["team_batting_name"]  == "Aston on Trent 1st XI"
    assert inn2["team_fielding_name"] == "Etwall CC Hawks"


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


def test_last_wicket_id_increments_on_dismissal():
    acc = MatchAccumulator()
    acc.apply("BTS", "10/1")
    acc.apply("LWK", "10")
    acc.apply("LWN", "A Adams")
    assert acc.snapshot().last_wicket_id == 1
    acc.apply("BTS", "25/2")
    acc.apply("LWK", "25")
    acc.apply("LWN", "B Brown")
    assert acc.snapshot().last_wicket_id == 2


def test_match_detail_envelope_carries_last_event():
    acc = MatchAccumulator()
    acc.apply("COV", "4 ")
    acc.apply("LWK", "4")
    acc.apply("LWN", "A Adams")
    env = serializers.match_detail_envelope(acc.snapshot())
    le = env["match_details"][0]["last_event"]
    assert le == {
        "ball_id":        1,
        "ball_runs":      4,
        "ball_is_wicket": False,
        "wicket_id":      1,
    }


# ---------- operator manual team-name overrides -------------------------------

def test_override_pins_name_over_later_app_name():
    """A manual home name wins over whatever BTN/FTN the app sends afterwards."""
    acc = MatchAccumulator()
    acc.set_team_names(home="Aston 1st XI", away="")
    acc.apply("BTN", "PC Home")                    # app names arrive after
    acc.apply("FTN", "PC Away")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston 1st XI"   # override wins
    assert snap.away_team_name == "PC Away"        # no override -> app name


def test_override_both_sides_wins_over_app():
    acc = MatchAccumulator()
    acc.apply("BTN", "PC Home")
    acc.apply("FTN", "PC Away")
    acc.set_team_names(home="Aston 1st XI", away="Repton CC")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston 1st XI"
    assert snap.away_team_name == "Repton CC"


def test_blank_override_reverts_that_side_to_app_name():
    acc = MatchAccumulator()
    acc.apply("BTN", "PC Home")
    acc.apply("FTN", "PC Away")
    acc.set_team_names(home="Aston 1st XI", away="Repton CC")
    assert acc.snapshot().home_team_name == "Aston 1st XI"
    acc.set_team_names(home="", away="Repton CC")  # blank the home box
    snap = acc.snapshot()
    assert snap.home_team_name == "PC Home"         # reverted to app name
    assert snap.away_team_name == "Repton CC"       # still pinned


def test_override_drives_display_before_any_app_name():
    """Pre-match: the operator can name a side before any BTN/FTN arrives; the
    un-named side stays blank (no placeholder)."""
    acc = MatchAccumulator()
    acc.set_team_names(home="Aston 1st XI", away="")
    snap = acc.snapshot()
    assert snap.home_team_name == "Aston 1st XI"
    assert snap.away_team_name == ""


def test_reset_clears_overrides():
    acc = MatchAccumulator()
    acc.set_team_names(home="Aston 1st XI", away="Repton CC")
    acc.reset()
    snap = acc.snapshot()
    assert snap.home_team_name_override == ""
    assert snap.away_team_name_override == ""
    assert snap.home_team_name == ""
    assert snap.away_team_name == ""
