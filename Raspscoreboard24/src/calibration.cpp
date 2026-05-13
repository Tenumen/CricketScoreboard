#include "calibration.h"
#include "grid_canvas.h"
#include "panel_layout.h"

#include "led-matrix.h"
#include "graphics.h"

#include <unistd.h>
#include <cstdio>

namespace cricketboard {

namespace {

constexpr int kHoldMicros = 1500 * 1000;  // 1.5s per panel in sequential mode

// Per-row background colour so swapped chains stand out at a glance.
rgb_matrix::Color RowColour(int grid_row_idx) {
    switch (grid_row_idx) {
        case 0: return rgb_matrix::Color(128,   0,   0);  // A — red
        case 1: return rgb_matrix::Color(  0, 110,   0);  // B — green
        case 2: return rgb_matrix::Color(  0,   0, 140);  // C — blue
        case 3: return rgb_matrix::Color(110,  85,   0);  // D — yellow/amber
        default: return rgb_matrix::Color(64, 64, 64);
    }
}

// Print a label centred inside a 64x64 logical panel anchored at (px, py).
void DrawPanelLabel(rgb_matrix::Canvas *c,
                    const rgb_matrix::Font &font,
                    int px, int py,
                    const char *label) {
    const int label_pixels = font.CharacterWidth('A') * 2;  // "A1" etc.
    const int x = px + (kPanelPx - label_pixels) / 2;
    const int y = py + (kPanelPx - font.height()) / 2 + font.baseline();
    rgb_matrix::Color white(255, 255, 255);
    DrawText(c, font, x, y, white, nullptr, label, 0);
}

// Mark the top-left of the panel's logical region with a small L bracket.
// If the panel is oriented correctly, this bracket appears in the physical
// top-left of the panel as you read the label. If it appears bottom-right,
// the panel needs its rotation flipped 0 <-> 180.
void DrawOrientationMark(rgb_matrix::Canvas *c, int px, int py) {
    rgb_matrix::Color w(255, 255, 255);
    // Horizontal stroke of the L (top edge)
    for (int dx = 0; dx < 10; ++dx) c->SetPixel(px + dx, py + 0, w.r, w.g, w.b);
    // Vertical stroke of the L (left edge)
    for (int dy = 0; dy < 10; ++dy) c->SetPixel(px + 0, py + dy, w.r, w.g, w.b);
}

void PaintPanel(GridCanvas *c,
                const rgb_matrix::Font &font,
                int grid_row_idx, int grid_col_one_based) {
    const int panel_col_lr = kGridCols - grid_col_one_based;  // col 1 -> rightmost
    const int px = panel_col_lr * kPanelPx;
    const int py = grid_row_idx * kPanelPx;

    rgb_matrix::Color bg = RowColour(grid_row_idx);
    for (int dy = 0; dy < kPanelPx; ++dy)
        for (int dx = 0; dx < kPanelPx; ++dx)
            c->SetPixel(px + dx, py + dy, bg.r, bg.g, bg.b);

    DrawOrientationMark(c, px, py);

    char label[4] = { static_cast<char>('A' + grid_row_idx),
                      static_cast<char>('0' + grid_col_one_based),
                      0, 0 };
    DrawPanelLabel(c, font, px, py, label);
}

}  // namespace

void RunCalibration(rgb_matrix::RGBMatrix *matrix,
                    const rgb_matrix::Font &label_font,
                    CalibrationMode mode,
                    volatile bool *interrupt_flag) {
    rgb_matrix::FrameCanvas *frame = matrix->CreateFrameCanvas();
    GridCanvas grid(frame);

    if (mode == CalibrationMode::AllAtOnce) {
        printf("Calibration: all panels labelled. Ctrl+C to exit.\n");
        while (!*interrupt_flag) {
            grid.Fill(0, 0, 0);
            for (int r = 0; r < kGridRows; ++r)
                for (int c = 1; c <= kGridCols; ++c)
                    PaintPanel(&grid, label_font, r, c);
            frame = matrix->SwapOnVSync(frame);
            grid.set_backing(frame);
            usleep(200 * 1000);
        }
        return;
    }

    printf("Calibration: lighting one panel at a time. Ctrl+C to exit.\n");
    while (!*interrupt_flag) {
        for (int r = 0; r < kGridRows && !*interrupt_flag; ++r) {
            for (int col = 1; col <= kGridCols && !*interrupt_flag; ++col) {
                grid.Fill(0, 0, 0);
                PaintPanel(&grid, label_font, r, col);
                frame = matrix->SwapOnVSync(frame);
                grid.set_backing(frame);
                usleep(kHoldMicros);
            }
        }
    }
}

}  // namespace cricketboard
