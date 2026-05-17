// frame_emitter.h — async libcurl POST helper. Single dedicated thread, single-
// slot queue with drop-oldest-on-full semantics, so the render path is never
// blocked by network. Used by the headless backend, optionally by the hub75
// backend when CRICKETBOARD_EMIT_FRAMES is defined.

#ifndef RASPSCOREBOARD24_RENDER_BACKEND_FRAME_EMITTER_H
#define RASPSCOREBOARD24_RENDER_BACKEND_FRAME_EMITTER_H

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace cricketboard {

class FrameEmitter {
public:
    // base_url like "http://192.168.1.42:5050" — the POST target will be
    // base_url + "/api/sim/frame".
    FrameEmitter(std::string base_url, int width, int height,
                 bool send_on_change_only);
    ~FrameEmitter();

    FrameEmitter(const FrameEmitter&) = delete;
    FrameEmitter& operator=(const FrameEmitter&) = delete;

    // Hand a frame off to the emitter thread. Cheap — copies the bytes into
    // the single-slot queue and signals the thread. If a frame is already
    // queued (network is slow / endpoint is down), the new frame replaces it.
    void queue_frame(const std::vector<uint8_t> &bytes);

private:
    void run();

    const std::string  endpoint_url_;
    const int          width_;
    const int          height_;
    const bool         send_on_change_only_;

    std::mutex              mu_;
    std::condition_variable cv_;
    std::vector<uint8_t>    pending_;   // empty = no frame queued
    std::vector<uint8_t>    last_sent_;
    bool                    quit_ = false;
    uint64_t                frame_no_ = 0;

    std::thread             thread_;
    std::atomic<int>        consecutive_errors_{0};
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_RENDER_BACKEND_FRAME_EMITTER_H
