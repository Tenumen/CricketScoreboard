"""Entry point: wire BLE peripheral + accumulator + Flask HTTP server.

The HTTP server runs in a worker thread (Flask is sync); the BLE peripheral
runs in the asyncio loop on the main thread. They share a thread-safe
MatchAccumulator.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading

from .state import MatchAccumulator
from .http_server import create_app
from .ble_peripheral import run_peripheral


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


def _start_http(accumulator: MatchAccumulator, host: str, port: int,
                allow_inject: bool) -> threading.Thread:
    app = create_app(accumulator, allow_inject=allow_inject)

    def _run():
        # Flask's dev server is fine here — only ever local, single client.
        app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, name="http-server", daemon=True)
    t.start()
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="playcricket_ble_bridge")
    ap.add_argument("--host", default="127.0.0.1",
                    help="HTTP bind address (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=5051,
                    help="HTTP bind port (default: 5051)")
    ap.add_argument("--our-club-id", type=int, default=0,
                    help="Our club's Play-Cricket site id (so 'home' / 'opponent' resolves correctly on the wall)")
    ap.add_argument("--our-team-name", default="Aston",
                    help="Name fragment that identifies our club among the app's "
                         "batting/fielding team names, so its real name maps to the "
                         "home slot (case-insensitive; default: 'Aston')")
    ap.add_argument("--discovery-log",
                    default=os.environ.get("BRIDGE_DISCOVERY_LOG", "discovery.log"),
                    help="Append every received BLE token here (default: ./discovery.log)")
    ap.add_argument("--no-ble", action="store_true",
                    help="Skip BLE — useful for local HTTP-only testing")
    ap.add_argument("--allow-inject", action="store_true",
                    help="Expose POST /api/sim/inject for dev token injection (no BLE phone needed)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    _setup_logging(args.verbose)
    log = logging.getLogger("playcricket_ble_bridge")

    accumulator = MatchAccumulator(our_club_id=args.our_club_id,
                                   our_team_name=args.our_team_name)
    _start_http(accumulator, args.host, args.port, allow_inject=args.allow_inject)
    log.info("HTTP server listening on http://%s:%d", args.host, args.port)
    log.info("  result_summary: http://%s:%d/api/v2/result_summary.json", args.host, args.port)
    log.info("  match_detail:   http://%s:%d/api/v2/match_detail.json",   args.host, args.port)

    if args.no_ble:
        log.info("BLE disabled (--no-ble). HTTP only; press Ctrl-C to exit.")
        try:
            signal.pause()
        except KeyboardInterrupt:
            pass
        return 0

    stop_event = asyncio.Event()

    def _on_signal(signum, _frame):
        log.info("signal %d received, shutting down", signum)
        try:
            asyncio.get_event_loop().call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        asyncio.run(run_peripheral(accumulator, args.discovery_log, stop_event))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
