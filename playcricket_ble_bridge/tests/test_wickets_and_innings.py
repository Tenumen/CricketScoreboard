"""Regression tests for the 2026-07-13 pipeline review fixes.

Covers: (1) a mid-innings BTN rename must not open a phantom 2nd innings
(only a flip to the fielding side does); (3) a second wicket at the same
team score — where the app OMITS LWK because the value is unchanged — must
still register (fow entry + last_wicket_id bump for the splash); (4) a
stale-suppressed wicket cluster's LWS/LWD must not decorate (corrupt) the
previous dismissed batter's entry.

The wicket sequences mirror pi_pull_20260711/discovery.log 2026-05-31T10:26,
where wickets 6 and 7 both fell at 63 and the second cluster arrived with no
LWK token.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playcricket_ble_bridge.state import MatchAccumulator


# ---------- (3) same-score consecutive wickets ---------------------------------

def test_second_wicket_at_same_score_fires_and_records():
    """Real log 10:26: 63/6 then 63/7 next ball; the app dedupes unchanged
    token values so the second cluster has NO LWK. The wicket must still bump
    last_wicket_id (splash) and append a fow entry."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston")
    acc.apply("FTN", "Away")
    # 6th wicket at 63 (full cluster).
    acc.apply("OVB", "7.1")
    acc.apply("BTS", "63/6")
    acc.apply("LWK", "63")
    acc.apply("LWN", "F F")
    acc.apply("LWS", "1 (2)")
    w_after_first = acc.snapshot().last_wicket_id
    # 7th wicket next ball, same score — LWK omitted by the app.
    acc.apply("OVB", "7.2")
    acc.apply("BTS", "63/7")
    acc.apply("LWN", "E E")
    acc.apply("LWS", "0 (1)")
    acc.apply("LWD", "c")

    s = acc.snapshot()
    assert s.last_wicket_id == w_after_first + 1
    fow = s.innings[-1].fow
    assert [f.runs for f in fow] == [63, 63]
    assert fow[1].batsman_out_name == "E E"
    assert fow[1].how_out == "caught"
    dismissed = s.innings[-1].dismissed
    assert [(b.batsman_name, b.runs) for b in dismissed] == [("F F", 1), ("E E", 0)]


def test_replayed_cluster_is_not_a_second_wicket():
    """On reconnect the app re-sends the whole last-wicket cluster verbatim;
    the same LWN name must not register a duplicate."""
    acc = MatchAccumulator()
    acc.apply("BTS", "58/1")
    acc.apply("LWK", "58")
    acc.apply("LWN", "B B")
    acc.apply("LWS", "27 (16)")
    acc.apply("LWD", "b")
    w1 = acc.snapshot().last_wicket_id
    # Verbatim replay.
    acc.apply("BTS", "58/1")
    acc.apply("LWK", "58")
    acc.apply("LWN", "B B")
    acc.apply("LWS", "27 (16)")
    acc.apply("LWD", "b")
    s = acc.snapshot()
    assert s.last_wicket_id == w1
    assert len(s.innings[-1].fow) == 1
    assert len(s.innings[-1].dismissed) == 1


# ---------- (4) stale cluster must not corrupt the previous entry --------------

def test_stale_cluster_lws_lwd_do_not_touch_previous_batter():
    """A wicket falls while the BLE link is down; on reconnect BTS arrives
    first (real cluster order), so the replayed LWK reads below the live total
    and the cluster is classified stale. Its LWS/LWD used to overwrite the
    PREVIOUS dismissed batter's runs/balls/how_out — they must now be inert."""
    acc = MatchAccumulator()
    # A live wicket the bridge saw normally.
    acc.apply("BTS", "40/1")
    acc.apply("LWK", "40")
    acc.apply("LWN", "A Adams")
    acc.apply("LWS", "10 (20)")
    acc.apply("LWD", "b")
    w1 = acc.snapshot().last_wicket_id
    # Link drops; play moves on; reconnect replays state: total first...
    acc.apply("BTS", "80/2")
    # ...then the wicket-that-fell-offline's cluster (fall score 55 < 80).
    acc.apply("LWK", "55")
    acc.apply("LWN", "B Brown")
    acc.apply("LWS", "5 (9)")
    acc.apply("LWD", "ro")

    s = acc.snapshot()
    inn = s.innings[-1]
    # The stale cluster registered nothing and fired no splash...
    assert s.last_wicket_id == w1
    assert len(inn.fow) == 1
    assert [b.batsman_name for b in inn.dismissed] == ["A Adams"]
    # ...and crucially left A Adams' entry untouched.
    assert inn.dismissed[0].runs == 10
    assert inn.dismissed[0].balls == 20
    assert inn.dismissed[0].how_out == "bowled"
    assert inn.fow[0].how_out == "bowled"


def test_live_wicket_after_stale_cluster_registers_normally():
    """The stale flag must clear on the next genuine cluster (LWK == total)."""
    acc = MatchAccumulator()
    acc.apply("BTS", "80/2")
    acc.apply("LWK", "55")          # stale replay
    acc.apply("LWN", "B Brown")
    # Next real wicket at the live total.
    acc.apply("BTS", "80/3")
    acc.apply("LWK", "80")
    acc.apply("LWN", "C Clark")
    acc.apply("LWS", "12 (15)")
    s = acc.snapshot()
    assert s.last_wicket_id == 1
    assert [b.batsman_name for b in s.innings[-1].dismissed] == ["C Clark"]
    assert s.innings[-1].dismissed[0].runs == 12


# ---------- (1) rename vs genuine innings flip ----------------------------------

def test_mid_innings_rename_does_not_open_second_innings():
    """Real logs show scorers renaming a side mid-game ('Aston Test' ->
    'Aston On Trent'). A BTN that matches neither the batting nor fielding
    side is a rename: apply it in place, never open innings 2."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston Test")
    acc.apply("FTN", "Opponents")
    acc.apply("BTS", "50/2")
    acc.apply("OVB", "10.0")
    acc.apply("BTN", "Aston On Trent")      # correction, not a flip
    s = acc.snapshot()
    assert len(s.innings) == 1
    assert s.innings[0].team_batting_name == "Aston On Trent"
    assert s.innings[0].runs == 50
    assert s.home_team_name == "Aston On Trent"
    # Play continues into innings 1 — and no phantom result appears.
    acc.apply("BTS", "60/2")
    assert acc.snapshot().result == ""
    # The real flip later (new BTN == the fielding side) still opens innings 2.
    acc.apply("BTN", "Opponents")
    assert len(acc.snapshot().innings) == 2
    assert acc.snapshot().innings[1].team_batting_name == "Opponents"


def test_flip_still_opens_when_ftn_never_arrived():
    """Without an FTN we cannot tell a flip from a rename; keep the old
    open-on-any-change behaviour rather than absorb a real innings change."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("BTS", "180/8")
    acc.apply("BTN", "Melbourne")
    assert len(acc.snapshot().innings) == 2


def test_pre_play_team_swap_does_not_open_second_innings():
    """Teams entered the wrong way round and corrected before a ball is
    bowled: even a BTN matching the fielding side is a correction, not a
    flip, while innings 1 has no activity."""
    acc = MatchAccumulator()
    acc.apply("BTN", "Aston on Trent")
    acc.apply("FTN", "Melbourne")
    acc.apply("BTN", "Melbourne")           # swap fix at 0/0, 0.0 overs
    s = acc.snapshot()
    assert len(s.innings) == 1
    assert s.innings[0].team_batting_name == "Melbourne"
