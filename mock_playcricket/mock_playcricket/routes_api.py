"""Play-Cricket-mirror API routes (/api/v2/*).

These mirror the real endpoints exactly so a client built against play-cricket
can switch between mock and real by changing only the base URL. api_token
and site_id are accepted but ignored.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from . import serializers as ser

bp = Blueprint("api_v2", __name__, url_prefix="/api/v2")


def _ctx():
    return current_app.config["CTX"]


@bp.get("/matches.json")
def matches_json():
    ctx = _ctx()
    with ctx.lock:
        items = [ser.match_summary_to_dict(m) for m in ctx.store.matches.values()]
    return jsonify({"matches": items})


@bp.get("/result_summary.json")
def result_summary_json():
    """Fixture-discovery endpoint the Pi client polls.

    The Pi's PickMatchIdFromResultSummary reads the FIRST entry's id and locks
    on to it for the rest of the run. So for the mock to be useful, this
    endpoint must return the ACTIVE match first (or only). If no match is
    active, return every match so the client can at least find something."""
    ctx = _ctx()
    with ctx.lock:
        active = ctx.store.active()
        if active is not None:
            items = [ser.match_summary_to_dict(active)]
        else:
            items = [ser.match_summary_to_dict(m) for m in ctx.store.matches.values()]
    return jsonify({"result_summary": items})


@bp.get("/match_detail.json")
def match_detail_json():
    ctx = _ctx()
    try:
        match_id = int(request.args.get("match_id", ""))
    except ValueError:
        return jsonify({"match_details": []})
    with ctx.lock:
        m = ctx.store.matches.get(match_id)
        if m is None:
            return jsonify({"match_details": []})
        return jsonify({"match_details": [ser.match_detail_to_dict(m)]})
