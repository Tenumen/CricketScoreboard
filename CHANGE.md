# Changelog

## 2026-05-15 — Brighten WKTS red for readability

- **Changed:** `Raspscoreboard24/src/main.cpp` — `Color c_red` from `(255, 60, 60)` to `(255, 110, 110)`; used only for the WKTS number in row-B-right cell.
- **Why:** Pure saturated red on HUB75 at brightness=50 was too dim at distance — only one of three subpixels fires. Lifting the off-channels to 110 adds luminance (now reads as vivid coral) while keeping the hue unambiguously red.
- **Heuristic:** If any LED colour reads dim despite full saturation, add 30–60 to the off channels. Likely applies to the green OVERS number and amber numbers if they need similar treatment.
- **Commits:** uncommitted
- **Next:** Per-panel rotation verification; then implement Rows 1–3 on the 384×256 canvas per DISPLAY_NOTES_24.md.

## 2026-05-13 — 24-panel wall calibration complete

- **Changed:** `Raspscoreboard24/src/grid_canvas.cpp` — removed incorrect row flip (`grid_row_idx = (kGridRows-1) - panel_row_tb` reverted to `grid_row_idx = panel_row_tb`); row A (red) already placed correctly at physical bottom without the flip.
- **Changed:** `Raspscoreboard24/src/panel_layout.h` — corrected B/C corner chain assignment: B1/B6 on `kParBottom` (pos 0, 7); C1/C6 on `kParTop` (pos 0, 7); corrected middle chain interior order to B2,C2,C3,B3,B4,C4,C5,B5; B interior maps to kParMiddle pos 0,3,4,7; C interior maps to kParMiddle pos 1,2,5,6.
- **Changed:** `Raspscoreboard/README.md` — deprecation banner added.
- **Why:** All 24 panels now display correct row colours in `--calibrate=all` mode. Layout confirmed end-to-end.
- **Commits:** `1fc88c8` ("Add Raspscoreboard24 fork for 24-panel 6x4 HUB75E wall") — pushed to main.
- **Next:** Per-panel rotation verification (sequential `--calibrate` mode; any upside-down panel → set rotation=180 in panel_layout.h). Then implement Rows 1–3 (OVERS/RUNS/WKTS, BAT 1/BAT 2, idle/splash) on the 384×256 canvas per DISPLAY_NOTES_24.md spec.

