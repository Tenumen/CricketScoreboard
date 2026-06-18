"""Flask app exposing the bridge's accumulated MatchState as a Play-Cricket
HTTP API on localhost. The scoreboard24 C++ binary polls this exactly as it
would poll play-cricket.com — same paths, same JSON envelope.

Two paths only:
  /api/v2/result_summary.json   — used to discover the match id
  /api/v2/match_detail.json     — used to fetch the full state every poll

Query parameters (`site_id`, `from_match_date`, `api_token`, etc.) are
accepted and ignored — this is a single-match service backed by whatever the
BLE peripheral has heard from the phone since boot.
"""
from __future__ import annotations

from flask import Flask, jsonify, request

from . import serializers
from .state import MatchAccumulator


def create_app(accumulator: MatchAccumulator, allow_inject: bool = False) -> Flask:
    app = Flask(__name__)

    @app.get("/api/v2/result_summary.json")
    def result_summary():
        snap = accumulator.snapshot()
        return jsonify(serializers.result_summary_envelope(snap))

    @app.get("/api/v2/match_detail.json")
    def match_detail():
        snap = accumulator.snapshot()
        return jsonify(serializers.match_detail_envelope(snap))

    @app.get("/api/sim/info")
    def info():
        snap = accumulator.snapshot()
        return jsonify({
            "generation":     accumulator.generation,
            "match_id":       snap.id,
            "home_team":      snap.home_team_name,
            "away_team":      snap.away_team_name,
            "innings_count":  len(snap.innings),
            "unknown_codes":  accumulator.unknown_codes(),
        })

    # Operator overrides for the post-match (winner) splash. The BLE feed
    # never signals "match over", so the result is normally auto-inferred from
    # the score; these let the operator force or undo it from the admin console
    # (which proxies here over localhost). Always on — this is an operator
    # feature, not a dev-only inject.
    @app.post("/api/admin/finish")
    def admin_finish():
        return jsonify(accumulator.force_finish())

    @app.post("/api/admin/reopen")
    def admin_reopen():
        return jsonify(accumulator.reopen())

    # Freeze an innings-summary screen at the interval (Total/Extras/Wickets +
    # top two batters). The BLE feed sends no innings-over signal, so this is a
    # manual button; auto-clears when the next innings resumes play.
    @app.post("/api/admin/innings-finished")
    def admin_innings_finished():
        return jsonify(accumulator.finish_innings())

    # Clear the match back to a clean slate (idle logo, ready for a new game);
    # and force the live 0/0 board on before any score arrives. Both proxied
    # from the admin console, same as finish/reopen.
    @app.post("/api/admin/reset")
    def admin_reset():
        return jsonify(accumulator.reset())

    @app.post("/api/admin/blank")
    def admin_blank():
        return jsonify(accumulator.blank_scoreboard())

    # Operator-typed team names from the admin console. A non-empty name pins
    # that side over whatever the app sends; an empty string reverts that side
    # to the app's name. Proxied from the console, same as the commands above.
    @app.post("/api/admin/team-names")
    def admin_team_names():
        body = request.get_json(silent=True) or {}
        return jsonify(accumulator.set_team_names(
            home=body.get("home_team_name", ""),
            away=body.get("away_team_name", "")))

    if allow_inject:
        # Dev-only: simulate a BLE token without a phone. Body =
        # {"code": "BTS", "value": "245/3"} or a list of such objects.
        @app.post("/api/sim/inject")
        def inject():
            body = request.get_json(silent=True)
            if body is None:
                return jsonify({"error": "json body required"}), 400
            items = body if isinstance(body, list) else [body]
            applied = 0
            for it in items:
                code  = (it.get("code")  or "")[:3]
                value = it.get("value") or ""
                if not code:
                    continue
                if accumulator.apply(code, str(value)):
                    applied += 1
            return jsonify({"applied": applied, "generation": accumulator.generation})

    return app
