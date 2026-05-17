# mock_playcricket

A local Flask server that mimics the Play-Cricket HTTP API and provides a
web-based scoring UI plus a 24-panel scoreboard visualizer.

Lets you develop and test the Raspberry Pi scoreboard end-to-end without
needing a real fixture on play-cricket.com, the Pi hardware, or the HUB75 wall.

## Quick start

```bash
cd mock_playcricket
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

python -m mock_playcricket            # default: 0.0.0.0:5050, state.json next to package
```

Open:
- `http://<host>:5050/`            — scoring UI
- `http://<host>:5050/visualizer`  — 24-panel display visualizer

## API endpoints

**Play-Cricket mirror** (point the Pi/sim binary at these by setting
`api_base_url` in its config):

| Path | Notes |
|---|---|
| `GET /api/v2/matches.json` | Same shape as play-cricket.com |
| `GET /api/v2/match_detail.json?match_id=...` | Same shape, full innings/players |
| `GET /api/v2/result_summary.json` | Same fixture list, different envelope (the existing Pi client uses this) |

`api_token` and `site_id` query params are accepted and ignored.

**Sim frame ingest** (called by the Pi binary's headless backend):

| Path | Notes |
|---|---|
| `POST /api/sim/frame` | Body = raw RGB bytes, `X-Frame-Width/-Height` headers required |
| `GET  /api/sim/frame.png` | Latest frame, reverse-mapped to 384×256 logical canvas |
| `GET  /api/sim/info` | JSON: has_frame, frame_number, dimensions |

**Scoring UI control** (used by the browser):

| Path | Notes |
|---|---|
| `GET /api/ui/state` | Full state + view-model |
| `POST /api/ui/new-match` | Create a fixture |
| `POST /api/ui/start-innings` | Open the next innings |
| `POST /api/ui/ball` | Apply one delivery |
| `POST /api/ui/change-bowler` | Mid-innings bowler change |
| `POST /api/ui/edit` | Direct-edit patch |
| `POST /api/ui/end-innings` | Close current innings (declared/forfeited supported) |
| `POST /api/ui/end-match` | Finalise the result |
| `POST /api/ui/set-active-match` | Switch the active match |
| `POST /api/ui/delete-match` | Remove a match from the store |

## CLI flags

```
python -m mock_playcricket --host 0.0.0.0 --port 5050 --state-file ./state.json
```

State persists to JSON between restarts (atomic write). Add `state.json` to
your `.gitignore` (already done within this package).

## Out of scope

- API token validation, rate limiting.
- Concurrent multi-match scoring (one active match at a time).
- Real-time push to the Pi (the Pi polls; the visualizer polls).
- Ball-by-ball historical replay export.
- Authentication on the UI (anyone on the LAN can score).

## Sync notes

`mock_playcricket/panel_layout.py` mirrors `Raspscoreboard24/src/panel_layout.h`.
If you edit one, edit both — the visualizer uses the Python copy to reverse the
logical → hardware mapping the Pi does.
