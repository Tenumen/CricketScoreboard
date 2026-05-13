// panel_layout.h — physical wiring of the 24-panel 6x4 grid.
//
// Edit this file (and rebuild) when calibration shows a panel in the wrong place
// or with the wrong orientation. The runtime code reads `kPanelLayout` and
// translates logical pixel coordinates into hardware (parallel, chain_pos, local)
// coordinates accordingly.

#ifndef RASPSCOREBOARD24_PANEL_LAYOUT_H
#define RASPSCOREBOARD24_PANEL_LAYOUT_H

namespace cricketboard {

// Logical canvas (front-view): 6 panels wide x 4 panels tall = 384 x 256 px.
// Row A is at the top, row D at the bottom. Column 1 is on the right, column 6
// on the left, so within each row the panels read right-to-left in column order.
constexpr int kPanelPx       = 64;
constexpr int kGridCols      = 6;
constexpr int kGridRows      = 4;
constexpr int kLogicalWidth  = kGridCols * kPanelPx;  // 384
constexpr int kLogicalHeight = kGridRows * kPanelPx;  // 256

// Hardware canvas: 3 parallel chains of 8 panels each = 512 x 192.
constexpr int kChainLength  = 8;
constexpr int kParallelChains = 3;
constexpr int kHardwareWidth  = kChainLength * kPanelPx;     // 512
constexpr int kHardwareHeight = kParallelChains * kPanelPx;  // 192

// Which library-side `parallel` index each HAT silk-screen output maps to.
// Tune these if calibration shows the chains landing on the wrong rows.
// 2026-05-13: initial guess (0/1/2) put row A's data on row D's panels and vice
// versa — swapping BOTTOM and TOP fixed it.
constexpr int kParBottom = 2;
constexpr int kParMiddle = 1;
constexpr int kParTop    = 0;

struct PanelPlacement {
    int parallel;   // 0..2 (library parallel index)
    int chain_pos;  // 0..7 (position within that chain)
    int rotation;   // 0 or 180 (degrees, clockwise, in the panel's own frame)
};

// Indexed by [grid_row 0..3][grid_col 1..6 minus one].
// grid_row: 0=A (top of wall), 1=B, 2=C, 3=D (bottom).
//
// Chain orders (from the HAT, position 0 -> 7), as actually wired:
//   bottom: B1, A1, A2, A3, A4, A5, A6, B6
//   middle: B2, C2, C3, B3, B4, C4, C5, B5
//   top:    C1, D1, D2, D3, D4, D5, D6, C6
//
// All rotations start at 0; flip to 180 if a panel reads upside-down during
// calibration.
constexpr PanelPlacement kPanelLayout[kGridRows][kGridCols] = {
    // col1                col2                col3                col4                col5                col6
    // Row A
    { {kParBottom, 1, 0},  {kParBottom, 2, 0}, {kParBottom, 3, 0}, {kParBottom, 4, 0}, {kParBottom, 5, 0}, {kParBottom, 6, 0} },
    // Row B
    { {kParBottom, 0, 0},  {kParMiddle, 0, 0}, {kParMiddle, 3, 0}, {kParMiddle, 4, 0}, {kParMiddle, 7, 0}, {kParBottom, 7, 0} },
    // Row C
    { {kParTop,    0, 0},  {kParMiddle, 1, 0}, {kParMiddle, 2, 0}, {kParMiddle, 5, 0}, {kParMiddle, 6, 0}, {kParTop,    7, 0} },
    // Row D
    { {kParTop,    1, 0},  {kParTop,    2, 0}, {kParTop,    3, 0}, {kParTop,    4, 0}, {kParTop,    5, 0}, {kParTop,    6, 0} },
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_PANEL_LAYOUT_H
