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
