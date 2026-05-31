// backend.h — abstract render-backend seam.
//
// Two implementations are selected at build time:
//   hub75_backend.cpp     — drives the real HUB75 wall via rpi-rgb-led-matrix
//   headless_backend.cpp  — captures frames to RAM and POSTs them over HTTP
//
// Compile-time selection is via the RENDER_BACKEND make variable. Exactly one
// IDisplay implementation links into the final binary, so calls go straight
// through with no vtable cost beyond the virtual dispatch already paid for
// rgb_matrix::Canvas.

#ifndef RASPSCOREBOARD24_RENDER_BACKEND_BACKEND_H
#define RASPSCOREBOARD24_RENDER_BACKEND_BACKEND_H

#include <memory>
#include <string>

namespace rgb_matrix { class Canvas; }

namespace cricketboard {

struct DisplayOptions {
    // Common — set by main(), used by the hub75 backend; ignored by headless.
    int brightness            = 100;
    int pwm_bits              = 6;
    int gpio_slowdown         = 3;
    int limit_refresh_rate_hz = 120;
    int multiplexing          = 1;
    std::string hardware_mapping = "regular";

    // Headless / sim — used by the headless backend AND optionally by the
    // hub75 backend when built with EMIT_FRAMES=1 to mirror frames to a
    // visualizer over the LAN.
    std::string sim_endpoint;                       // empty = no emission
    bool        sim_send_on_change_only = true;
};

class IDisplay {
public:
    virtual ~IDisplay() = default;

    // The Canvas that should be drawn into for the next frame. After
    // swap_on_vsync(), this pointer may be different (double-buffering), so
    // callers should re-fetch it (or be holding a delegate that updates its
    // backing pointer in concert).
    virtual rgb_matrix::Canvas* current_back_buffer() = 0;

    // Push the back buffer to the display. For hub75 this is a real vsync
    // swap; for headless it serialises the buffer and queues an HTTP POST.
    virtual void swap_on_vsync() = 0;

    // Logical (rendered-into) canvas dimensions. Note: the back buffer's own
    // width()/height() may report the *hardware* dimensions (e.g. 512x192)
    // because the GridCanvas wrapper handles the logical->hardware mapping.
    virtual int width()  const = 0;
    virtual int height() const = 0;

    virtual void clear() = 0;
};

// Construct the backend selected at build time. Strips library-side flags
// from argv (HUB75 backend only). On HUB75 build, may return nullptr if the
// hardware init fails (e.g. not running as root).
std::unique_ptr<IDisplay> CreateDisplay(int *argc, char ***argv,
                                        const DisplayOptions &opts);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_RENDER_BACKEND_BACKEND_H
