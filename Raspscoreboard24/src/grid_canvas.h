// grid_canvas.h — a Canvas adapter that exposes the 24-panel wall as a 384x256
// logical surface, hiding the snake-chain wiring and per-panel rotation under
// SetPixel(). All hzeller graphics primitives (DrawText, DrawLine, SetImage,
// ...) accept rgb_matrix::Canvas* and so work directly against this class.

#ifndef RASPSCOREBOARD24_GRID_CANVAS_H
#define RASPSCOREBOARD24_GRID_CANVAS_H

#include "canvas.h"

namespace rgb_matrix { class FrameCanvas; }

namespace cricketboard {

class GridCanvas : public rgb_matrix::Canvas {
public:
    explicit GridCanvas(rgb_matrix::FrameCanvas *backing);

    int width() const override;
    int height() const override;

    void SetPixel(int x, int y, uint8_t r, uint8_t g, uint8_t b) override;
    void Clear() override;
    void Fill(uint8_t r, uint8_t g, uint8_t b) override;

    rgb_matrix::FrameCanvas *backing() const { return backing_; }
    void set_backing(rgb_matrix::FrameCanvas *backing) { backing_ = backing; }

private:
    rgb_matrix::FrameCanvas *backing_;
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_GRID_CANVAS_H
