// headless_backend.cpp — render to RAM, ship frames over HTTP. No HUB75
// hardware, no rpi-rgb-led-matrix runtime. Built when RENDER_BACKEND=headless.

#include "backend.h"
#include "frame_emitter.h"

#include "canvas.h"
#include "panel_layout.h"

#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

namespace cricketboard {

namespace {

// Byte-buffer Canvas: writes a single RGB pixel into a row-major W x H x 3 buf.
class ByteCanvas : public rgb_matrix::Canvas {
public:
    ByteCanvas(int w, int h) : w_(w), h_(h), buf_(size_t(w) * h * 3, 0) {}
    int width()  const override { return w_; }
    int height() const override { return h_; }
    void SetPixel(int x, int y, uint8_t r, uint8_t g, uint8_t b) override {
        if (x < 0 || x >= w_ || y < 0 || y >= h_) return;
        const size_t i = (size_t(y) * w_ + x) * 3;
        buf_[i + 0] = r;
        buf_[i + 1] = g;
        buf_[i + 2] = b;
    }
    void Clear() override { std::memset(buf_.data(), 0, buf_.size()); }
    void Fill(uint8_t r, uint8_t g, uint8_t b) override {
        for (size_t i = 0; i < buf_.size(); i += 3) {
            buf_[i + 0] = r; buf_[i + 1] = g; buf_[i + 2] = b;
        }
    }
    const std::vector<uint8_t> &bytes() const { return buf_; }
private:
    int w_, h_;
    std::vector<uint8_t> buf_;
};


class HeadlessDisplay : public IDisplay {
public:
    explicit HeadlessDisplay(const DisplayOptions &opts)
        : canvas_(kHardwareWidth, kHardwareHeight), opts_(opts) {
        if (!opts_.sim_endpoint.empty()) {
            emitter_ = std::make_unique<FrameEmitter>(opts_.sim_endpoint,
                                                      kHardwareWidth, kHardwareHeight,
                                                      opts_.sim_send_on_change_only);
        }
        std::fprintf(stderr,
            "headless backend: HW %dx%d, sim_endpoint='%s'%s\n",
            kHardwareWidth, kHardwareHeight,
            opts_.sim_endpoint.c_str(),
            opts_.sim_endpoint.empty() ? " (no frames will be sent)" : "");
    }
    ~HeadlessDisplay() override = default;

    rgb_matrix::Canvas *current_back_buffer() override { return &canvas_; }

    void swap_on_vsync() override {
        // Hand the bytes to the emitter (which makes its own copy / queue).
        if (emitter_) emitter_->queue_frame(canvas_.bytes());
        // No real swap — single buffer; main.cpp's optional second draw_phase
        // after the swap will rewrite the same content into this buffer.
    }

    int width()  const override { return kHardwareWidth; }
    int height() const override { return kHardwareHeight; }
    void clear() override { canvas_.Clear(); }

private:
    ByteCanvas canvas_;
    DisplayOptions opts_;
    std::unique_ptr<FrameEmitter> emitter_;
};

}  // namespace

std::unique_ptr<IDisplay> CreateDisplay(int * /*argc*/, char *** /*argv*/,
                                        const DisplayOptions &opts) {
    return std::unique_ptr<IDisplay>(new HeadlessDisplay(opts));
}

}  // namespace cricketboard
