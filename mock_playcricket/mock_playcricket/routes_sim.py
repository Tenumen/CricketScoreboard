"""Sim/visualizer endpoints. Frame ingest from the Pi binary and PNG serving
to the browser. Phase 3 of the implementation plan."""
from __future__ import annotations

import io
import time

from flask import Blueprint, abort, current_app, jsonify, request, send_file

from . import panel_layout as PL

bp = Blueprint("sim", __name__, url_prefix="/api/sim")


def _ctx():
    return current_app.config["CTX"]


@bp.post("/frame")
def frame_ingest():
    """Receive a raw RGB frame from the Pi/sim binary.

    Body: bytes, length = width * height * 3.
    Required headers: X-Frame-Width, X-Frame-Height. Optional: X-Frame-Number,
    X-Frame-Timestamp-Ms.
    """
    ctx = _ctx()
    try:
        width  = int(request.headers.get("X-Frame-Width", "0"))
        height = int(request.headers.get("X-Frame-Height", "0"))
    except ValueError:
        abort(400, "bad width/height headers")
    if width <= 0 or height <= 0:
        abort(400, "missing X-Frame-Width / X-Frame-Height")
    if width > 4096 or height > 4096:
        abort(400, "frame too large")

    body = request.get_data(cache=False, as_text=False)
    expected = width * height * 3
    if len(body) != expected:
        abort(400, f"body length {len(body)} != width*height*3 = {expected}")

    frame_no = 0
    try:
        frame_no = int(request.headers.get("X-Frame-Number", "0"))
    except ValueError:
        pass

    with ctx.frame_lock:
        ctx.frame_bytes = body
        ctx.frame_no    = frame_no
        ctx.frame_width = width
        ctx.frame_height = height
        ctx.frame_received_at = time.time()
    return ("", 204)


@bp.get("/frame.png")
def frame_serve():
    """Encode the latest frame as a PNG, reversing the panel-layout mapping
    back to the 384x256 logical canvas so the browser shows what the audience
    sees."""
    ctx = _ctx()
    with ctx.frame_lock:
        buf = ctx.frame_bytes
        w, h = ctx.frame_width, ctx.frame_height
        frame_no = ctx.frame_no
        received_at = ctx.frame_received_at if buf else 0
        age_ms = int((time.time() - ctx.frame_received_at) * 1000) if buf else -1

    if buf is None:
        # Return a tiny placeholder PNG (8x8 dark grey).
        try:
            from PIL import Image
        except Exception:
            abort(404)
        img = Image.new("RGB", (8, 8), (24, 24, 24))
        out = io.BytesIO(); img.save(out, "PNG"); out.seek(0)
        resp = send_file(out, mimetype="image/png", max_age=0)
        resp.headers["X-Frame-Number"] = "0"
        resp.headers["X-Frame-Age-Ms"] = "-1"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    try:
        from PIL import Image
    except Exception:
        abort(500, "Pillow not installed")

    # Hardware frame is 512x192; reverse-map to logical 384x256.
    logical = PL.hardware_to_logical(buf, w, h)
    img = Image.frombytes("RGB", (PL.LOGICAL_WIDTH, PL.LOGICAL_HEIGHT), bytes(logical))
    out = io.BytesIO(); img.save(out, "PNG"); out.seek(0)
    resp = send_file(out, mimetype="image/png", max_age=0)
    resp.headers["X-Frame-Number"] = str(frame_no)
    resp.headers["X-Frame-Age-Ms"] = str(age_ms)
    resp.headers["X-Frame-Received-At-Ms"] = str(int(received_at * 1000))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/info")
def info():
    ctx = _ctx()
    with ctx.frame_lock:
        return jsonify({
            "has_frame":     ctx.frame_bytes is not None,
            "frame_number":  ctx.frame_no,
            "width":         ctx.frame_width,
            "height":        ctx.frame_height,
            "received_at":   ctx.frame_received_at,
        })
