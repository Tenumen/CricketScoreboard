"""Entry point: python -m mock_playcricket"""
from __future__ import annotations

import argparse
import os
import socket
import sys

from .app import create_app


def lan_url(host: str, port: int) -> str:
    if host in ("0.0.0.0", "::"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return f"http://{ip}:{port}"
        except Exception:
            return f"http://127.0.0.1:{port}"
    return f"http://{host}:{port}"


def main() -> int:
    ap = argparse.ArgumentParser(prog="mock_playcricket")
    ap.add_argument("--host", default="0.0.0.0",
                    help="Bind host (default: 0.0.0.0 so the LAN can reach it)")
    ap.add_argument("--port", type=int, default=5050,
                    help="Bind port (default: 5050)")
    ap.add_argument("--state-file", default=None,
                    help="Path to state JSON (default: <pkg dir>/../state.json)")
    args = ap.parse_args()

    if args.state_file is None:
        here = os.path.dirname(os.path.abspath(__file__))
        args.state_file = os.path.abspath(os.path.join(here, "..", "state.json"))

    app = create_app(state_file=args.state_file)
    url = lan_url(args.host, args.port)
    print(f"\n  mock_playcricket listening on {url}")
    print(f"  Scoring UI:        {url}/")
    print(f"  Visualizer:        {url}/visualizer")
    print(f"  matches.json:      {url}/api/v2/matches.json")
    print(f"  match_detail.json: {url}/api/v2/match_detail.json?match_id=...")
    print(f"  result_summary:    {url}/api/v2/result_summary.json")
    print(f"  Frame ingest:      POST {url}/api/sim/frame")
    print(f"  State file:        {args.state_file}\n")
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
