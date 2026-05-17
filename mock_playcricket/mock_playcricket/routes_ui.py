"""UI-facing endpoints (separate namespace from /api/v2/* so the public surface
stays clean). These drive the scoring page."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, jsonify, render_template, request

from . import engine
from . import serializers as ser
from . import state as S

bp = Blueprint("ui", __name__)


def _ctx():
    return current_app.config["CTX"]


def _today_ddmmyyyy() -> str:
    return date.today().strftime("%d/%m/%Y")


def _find_player(m: S.MatchDetail, player_id: int) -> S.Player | None:
    for p in list(m.players_home) + list(m.players_away):
        if p.player_id == player_id:
            return p
    return None


def _build_view_model(ctx) -> dict:
    """View-model = full match dict + derived 'current' helpers so the JS
    can render without redoing engine logic."""
    out: dict = {"active_match_id": ctx.store.active_match_id,
                 "matches": [], "match": None, "view": None}
    for m in ctx.store.matches.values():
        out["matches"].append({"id": m.id,
                               "home_team_name": m.home_team_name,
                               "away_team_name": m.away_team_name,
                               "status": m.status,
                               "match_date": m.match_date})
    m = ctx.store.active()
    if m is None:
        return out
    out["match"] = ser.match_detail_to_dict(m)
    # The detail dict drops the engine-internal fields; the JS needs a few
    # of them for the controls, so expose them on `view`.
    cur_inn = next((i for i in m.innings if not i._closed), None)
    if cur_inn is None and m.innings:
        cur_inn = m.innings[-1]
    if cur_inn is not None:
        striker = next((b for b in cur_inn.bat if b.position == cur_inn._striker_pos), None)
        non_str = next((b for b in cur_inn.bat if b.position == cur_inn._non_striker_pos), None)
        bowler = (cur_inn.bowl[cur_inn._current_bowler_idx]
                  if 0 <= cur_inn._current_bowler_idx < len(cur_inn.bowl) else None)
        out["view"] = {
            "innings_number":   cur_inn.innings_number,
            "closed":           cur_inn._closed,
            "balls_this_over":  cur_inn._balls_this_over,
            "legal_balls":      cur_inn._legal_balls,
            "striker_pos":      cur_inn._striker_pos,
            "non_striker_pos":  cur_inn._non_striker_pos,
            "striker": {
                "name": striker.batsman_name, "runs": striker.runs, "balls": striker.balls
            } if striker else None,
            "non_striker": {
                "name": non_str.batsman_name, "runs": non_str.runs, "balls": non_str.balls
            } if non_str else None,
            "bowler": {
                "name": bowler.bowler_name,
                "bowler_id": bowler.bowler_id,
                "overs": f"{bowler._legal_balls // 6}.{bowler._legal_balls % 6}",
                "maidens": bowler.maidens, "runs": bowler.runs, "wickets": bowler.wickets,
            } if bowler else None,
            "target": (m.innings[0].runs + 1) if cur_inn.innings_number == 2 and m.innings else None,
        }
    return out


@bp.get("/")
def index():
    return render_template("scoring.html")


@bp.get("/visualizer")
def visualizer():
    return render_template("visualizer.html")


@bp.get("/api/ui/state")
def get_state():
    ctx = _ctx()
    with ctx.lock:
        return jsonify(_build_view_model(ctx))


@bp.post("/api/ui/new-match")
def new_match():
    ctx = _ctx()
    data = request.get_json(force=True)

    def _player_list(seed: list[str], id_base: int) -> list[S.Player]:
        return [S.Player(position=i + 1, player_name=name.strip(),
                         player_id=id_base + i + 1)
                for i, name in enumerate(seed) if name.strip()]

    with ctx.lock:
        mid = ctx.store.allocate_id()
        m = S.MatchDetail(
            id=mid,
            home_team_name=data.get("home_team_name", "Home"),
            away_team_name=data.get("away_team_name", "Away"),
            home_team_id=mid * 10 + 1,
            away_team_id=mid * 10 + 2,
            home_club_name=data.get("home_team_name", "Home"),
            away_club_name=data.get("away_team_name", "Away"),
            home_club_id=mid * 10 + 1,
            away_club_id=mid * 10 + 2,
            status="New",
            match_date=data.get("match_date") or _today_ddmmyyyy(),
            match_time=data.get("match_time", "13:00"),
            no_of_overs=int(data.get("no_of_overs", 20)),
            toss=data.get("toss", ""),
            batted_first=data.get("batted_first", ""),
            ground_name=data.get("ground_name", ""),
            players_home=_player_list(data.get("home_players", []), mid * 100),
            players_away=_player_list(data.get("away_players", []), mid * 100 + 50),
        )
        m.toss_won_by_team_id = (m.home_team_id if m.toss == m.home_team_name
                                 else (m.away_team_id if m.toss == m.away_team_name else 0))
        ctx.store.matches[mid] = m
        ctx.store.active_match_id = mid
        ctx.save()
    return jsonify({"ok": True, "match_id": mid})


@bp.post("/api/ui/set-active-match")
def set_active_match():
    ctx = _ctx()
    data = request.get_json(force=True)
    mid = int(data["match_id"])
    with ctx.lock:
        if mid not in ctx.store.matches:
            return jsonify({"ok": False, "error": "unknown match_id"}), 404
        ctx.store.active_match_id = mid
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/delete-match")
def delete_match():
    ctx = _ctx()
    data = request.get_json(force=True)
    mid = int(data["match_id"])
    with ctx.lock:
        ctx.store.matches.pop(mid, None)
        if ctx.store.active_match_id == mid:
            ctx.store.active_match_id = next(iter(ctx.store.matches.keys()), None)
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/start-innings")
def start_innings():
    ctx = _ctx()
    data = request.get_json(force=True)
    with ctx.lock:
        m = ctx.store.active()
        if m is None:
            return jsonify({"ok": False, "error": "no active match"}), 400
        innings_number = int(data["innings_number"])
        opener_ids = [int(x) for x in data["opening_bat_ids"]]
        bowler_id = int(data["opening_bowler_id"])
        # Resolve players
        team_batting_name = (m.batted_first if innings_number == 1
                             else (m.away_team_name if m.batted_first == m.home_team_name
                                   else m.home_team_name))
        team_batting_id = (m.home_team_id if team_batting_name == m.home_team_name
                           else m.away_team_id)
        # Openers come from the batting team's roster
        if team_batting_name == m.home_team_name:
            roster, opposing = m.players_home, m.players_away
        else:
            roster, opposing = m.players_away, m.players_home
        openers = []
        for oid in opener_ids:
            p = next((x for x in roster if x.player_id == oid), None)
            if p is None:
                return jsonify({"ok": False, "error": f"opener {oid} not on batting team"}), 400
            openers.append(p)
        bowler = next((x for x in opposing if x.player_id == bowler_id), None)
        if bowler is None:
            return jsonify({"ok": False, "error": "bowler not on bowling team"}), 400
        inn = engine.start_innings(m, innings_number, team_batting_name,
                                   team_batting_id, openers, bowler)
        m.innings.append(inn)
        m.status = "In progress"
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/ball")
def ball():
    ctx = _ctx()
    data = request.get_json(force=True)
    kind = data["kind"]
    runs = int(data.get("runs", 0))
    dismissal = data.get("dismissal")
    new_bowler_id = data.get("new_bowler_id")
    with ctx.lock:
        m = ctx.store.active()
        if m is None or not m.innings:
            return jsonify({"ok": False, "error": "no active innings"}), 400
        inn = next((i for i in m.innings if not i._closed), None)
        if inn is None:
            return jsonify({"ok": False, "error": "innings closed"}), 400
        # Resolve dismissal player names from IDs if needed
        if dismissal is not None and "new_batsman_id" in dismissal and "new_batsman_name" not in dismissal:
            p = _find_player(m, int(dismissal["new_batsman_id"]))
            if p:
                dismissal["new_batsman_name"] = p.player_name
        if dismissal is not None and "fielder_id" in dismissal and "fielder_name" not in dismissal:
            p = _find_player(m, int(dismissal["fielder_id"]))
            if p:
                dismissal["fielder_name"] = p.player_name
        engine.apply_ball(inn, m, kind, runs=runs, dismissal=dismissal)
        # End-of-over bowler change
        if new_bowler_id is not None and inn._balls_this_over == 0 and not inn._closed:
            p = _find_player(m, int(new_bowler_id))
            if p is not None:
                engine.change_bowler(inn, p)
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/change-bowler")
def change_bowler():
    ctx = _ctx()
    data = request.get_json(force=True)
    bid = int(data["bowler_id"])
    with ctx.lock:
        m = ctx.store.active()
        if m is None or not m.innings:
            return jsonify({"ok": False, "error": "no active innings"}), 400
        inn = next((i for i in m.innings if not i._closed), None)
        if inn is None:
            return jsonify({"ok": False, "error": "innings closed"}), 400
        p = _find_player(m, bid)
        if p is None:
            return jsonify({"ok": False, "error": "unknown bowler"}), 400
        engine.change_bowler(inn, p)
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/edit")
def edit():
    ctx = _ctx()
    data = request.get_json(force=True)
    with ctx.lock:
        m = ctx.store.active()
        if m is None or not m.innings:
            return jsonify({"ok": False, "error": "no active innings"}), 400
        innings_number = int(data.get("innings_number", m.innings[-1].innings_number))
        inn = next((i for i in m.innings if i.innings_number == innings_number), None)
        if inn is None:
            return jsonify({"ok": False, "error": "no such innings"}), 400
        engine.edit_innings(inn, data.get("patch", {}))
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/end-innings")
def end_innings():
    ctx = _ctx()
    data = request.get_json(force=True)
    with ctx.lock:
        m = ctx.store.active()
        if m is None or not m.innings:
            return jsonify({"ok": False, "error": "no active innings"}), 400
        inn = next((i for i in m.innings if not i._closed), None)
        if inn is None:
            return jsonify({"ok": False, "error": "all innings closed"}), 400
        engine.close_innings(inn,
                             declared=bool(data.get("declared", False)),
                             forfeited=bool(data.get("forfeited", False)))
        ctx.save()
    return jsonify({"ok": True})


@bp.post("/api/ui/end-match")
def end_match():
    ctx = _ctx()
    data = request.get_json(force=True)
    with ctx.lock:
        m = ctx.store.active()
        if m is None:
            return jsonify({"ok": False, "error": "no active match"}), 400
        m.status = "Result"
        m.result = data.get("result", "")
        m.result_description = data.get("result_description", "")
        m.result_applied_to = data.get("result_applied_to", "")
        for inn in m.innings:
            inn._closed = True
        ctx.save()
    return jsonify({"ok": True})
