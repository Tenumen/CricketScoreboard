#include "grid_canvas.h"
#include "panel_layout.h"

#include "led-matrix.h"

namespace cricketboard {

GridCanvas::GridCanvas(rgb_matrix::FrameCanvas *backing) : backing_(backing) {}

int GridCanvas::width()  const { return kLogicalWidth; }
int GridCanvas::height() const { return kLogicalHeight; }

void GridCanvas::Clear()                                 { backing_->Clear(); }
void GridCanvas::Fill(uint8_t r, uint8_t g, uint8_t b)   { backing_->Fill(r, g, b); }

void GridCanvas::SetPixel(int x, int y, uint8_t r, uint8_t g, uint8_t b) {
    if (x < 0 || x >= kLogicalWidth || y < 0 || y >= kLogicalHeight) return;

    // panel_col_lr: 0 is the leftmost panel column on screen (front view).
    // panel_row_tb: 0 is the top row of panels on screen (row A = bottom of wall).
    const int panel_col_lr = x / kPanelPx;
    const int panel_row_tb = y / kPanelPx;
    const int lx = x % kPanelPx;
    const int ly = y % kPanelPx;

    // Column 1 is on the right of the wall, column 6 on the left.
    const int grid_col_idx = (kGridCols - 1) - panel_col_lr;  // 0..5 -> col1..col6
    // Row A (index 0) is physically at the bottom of the wall; y=0..63 maps to row A,
    // y=192..255 maps to row D (top of wall). Direct mapping: no flip needed.
    const int grid_row_idx = panel_row_tb;
    const PanelPlacement &p = kPanelLayout[grid_row_idx][grid_col_idx];

    int out_x = lx;
    int out_y = ly;
    if (p.rotation == 180) {
        out_x = (kPanelPx - 1) - lx;
        out_y = (kPanelPx - 1) - ly;
    }

    const int hw_x = p.chain_pos * kPanelPx + out_x;
    const int hw_y = p.parallel  * kPanelPx + out_y;
    backing_->SetPixel(hw_x, hw_y, r, g, b);
}

}  // namespace cricketboard
