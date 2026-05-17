"""Flask app factory for the mock Play-Cricket server."""
from __future__ import annotations

import logging
import threading
from typing import Optional

from flask import Flask

from . import persistence
from . import state as S


class AppContext:
    """One-process holder for the match store, persistence path, and the latest
    sim frame buffer. Pinned to the Flask app via app.config['CTX']."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.store: S.MatchStore = persistence.load_store(state_file)
        self.lock = threading.RLock()

        # Sim frame ingest (Phase 3 — initialized empty so routes can probe)
        self.frame_lock = threading.Lock()
        self.frame_bytes: Optional[bytes] = None
        self.frame_no: int = 0
        self.frame_received_at: float = 0.0
        self.frame_width: int = 0
        self.frame_height: int = 0

    def save(self) -> None:
        """Persist the store. Caller is expected to hold self.lock."""
        persistence.save_store(self.store, self.state_file)


def create_app(state_file: str = "state.json") -> Flask:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    app.config["CTX"] = AppContext(state_file)

    from .routes_api import bp as api_bp
    from .routes_ui import bp as ui_bp
    from .routes_sim import bp as sim_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(ui_bp)
    app.register_blueprint(sim_bp)

    return app
