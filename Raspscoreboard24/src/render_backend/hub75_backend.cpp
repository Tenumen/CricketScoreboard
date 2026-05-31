// hub75_backend.cpp — drives the real HUB75 wall via rpi-rgb-led-matrix.
//
// Only built when RENDER_BACKEND=hub75. The Makefile excludes this file from
// the headless build so the binary doesn't pull in rpi-rgb-led-matrix.

#include "backend.h"

#include "led-matrix.h"
#include "graphics.h"

#include "panel_layout.h"

#include <cstdio>

#ifdef CRICKETBOARD_EMIT_FRAMES
#include "frame_emitter.h"
#include <cstring>
#endif

namespace cricketboard {

namespace {

using namespace rgb_matrix;

class Hub75Display : public IDisplay {
public:
    Hub75Display(RGBMatrix *matrix, FrameCanvas *frame, const DisplayOptions &opts)
        : matrix_(matrix), frame_(frame), opts_(opts) {
#ifdef CRICKETBOARD_EMIT_FRAMES
        if (!opts_.sim_endpoint.empty()) {
            emitter_ = std::make_unique<FrameEmitter>(opts_.sim_endpoint,
                                                      kHardwareWidth, kHardwareHeight,
                                                      opts_.sim_send_on_change_only);
        }
#endif
    }
    ~Hub75Display() override {
        if (matrix_) { matrix_->Clear(); delete matrix_; }
    }

    Canvas *current_back_buffer() override { return frame_; }

    void swap_on_vsync() override {
#ifdef CRICKETBOARD_EMIT_FRAMES
        if (emitter_) {
            // We don't have direct access to the FrameCanvas's pixel bytes;
            // re-read via Canvas::SetPixel/GetPixel isn't supported by
            // FrameCanvas. The user can run a headless build alongside for a
            // visualizer mirror — emitter on the hub75 binary is a stub today.
            // TODO: extend rpi-rgb-led-matrix to expose the pixel buffer if
            // we want true live mirroring from the Pi to the visualizer.
        }
#endif
        frame_ = matrix_->SwapOnVSync(frame_);
    }

    int width()  const override { return kHardwareWidth; }
    int height() const override { return kHardwareHeight; }
    void clear() override { frame_->Clear(); }

private:
    RGBMatrix   *matrix_;
    FrameCanvas *frame_;
    DisplayOptions opts_;
#ifdef CRICKETBOARD_EMIT_FRAMES
    std::unique_ptr<FrameEmitter> emitter_;
#endif
};

}  // namespace

std::unique_ptr<IDisplay> CreateDisplay(int *argc, char ***argv,
                                        const DisplayOptions &opts) {
    RGBMatrix::Options matrix_options;
    matrix_options.hardware_mapping = opts.hardware_mapping.c_str();
    matrix_options.rows         = kPanelPx;
    matrix_options.cols         = kPanelPx;
    matrix_options.chain_length = kChainLength;
    matrix_options.parallel     = kParallelChains;
    matrix_options.brightness   = opts.brightness;
    matrix_options.pwm_bits     = opts.pwm_bits;
    matrix_options.multiplexing = opts.multiplexing;
    matrix_options.show_refresh_rate     = false;
    matrix_options.limit_refresh_rate_hz = opts.limit_refresh_rate_hz;

    RuntimeOptions runtime_options;
    runtime_options.gpio_slowdown   = opts.gpio_slowdown;
    runtime_options.drop_privileges = -1;

    if (!ParseOptionsFromFlags(argc, argv, &matrix_options, &runtime_options)) {
        PrintMatrixFlags(stderr, matrix_options, runtime_options);
        return nullptr;
    }

    RGBMatrix *matrix = RGBMatrix::CreateFromOptions(matrix_options, runtime_options);
    if (matrix == nullptr) {
        std::fprintf(stderr, "Could not create matrix. Are you running as root?\n");
        return nullptr;
    }
    FrameCanvas *frame = matrix->CreateFrameCanvas();
    return std::unique_ptr<IDisplay>(new Hub75Display(matrix, frame, opts));
}

}  // namespace cricketboard
