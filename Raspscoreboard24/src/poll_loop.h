// poll_loop.h — background thread that fetches the live match state and
// publishes it to a SharedMatchState. One thread per process; safe to stop
// from the main thread via the `stop` flag passed at construction.

#ifndef RASPSCOREBOARD24_POLL_LOOP_H
#define RASPSCOREBOARD24_POLL_LOOP_H

#include <atomic>
#include <string>
#include <thread>

#include "match_state.h"

namespace cricketboard {

struct PollConfig {
    std::string api_token;
    int  club_site_id        = 0;
    int  poll_interval_secs  = 30;
    bool mock_mode            = true;
    std::string mock_data_path = "mock_data/mid_chase.json";

    // Base URL for the play-cricket API. Empty/absent => use the real
    // play-cricket.com host. Set to a mock server's URL (e.g. http://dev-box:5050)
    // to test against mock_playcricket.
    std::string api_base_url;

    // Sim frame emission (visualizer). Empty/null => don't emit. When set
    // (and EMIT_FRAMES is compiled in for the hub75 build, or RENDER_BACKEND=
    // headless), every SwapOnVSync POSTs the current frame to this URL.
    std::string sim_endpoint;
    bool        sim_endpoint_send_on_change_only = true;

    // Phone-accessible debug HTTP server. Disabled if password is empty.
    bool        debug_server_enabled  = true;
    int         debug_server_port     = 8080;
    std::string debug_server_password;

    // Where the running source tree and update/rollback helper scripts live
    // on the Pi. Defaults match what install_pi.sh configures.
    std::string repo_dir    = "/home/tenumen/scoreboard24";
    std::string scripts_dir = "/home/tenumen/scoreboard24/scripts";
};

// Read config from a JSON file. On failure, returns a default-constructed
// PollConfig and writes an explanation to stderr; the program can still run
// (mock_mode defaults to true with a sample path so a fresh checkout works
// even without a config file present).
PollConfig LoadConfig(const std::string& path);

class PollLoop {
public:
    // `state` and `stop` must outlive the PollLoop.
    PollLoop(PollConfig cfg, SharedMatchState* state, const volatile bool* stop);
    ~PollLoop();

    PollLoop(const PollLoop&) = delete;
    PollLoop& operator=(const PollLoop&) = delete;

    void start();
    void join();

private:
    void run();

    PollConfig         cfg_;
    SharedMatchState*  state_;
    const volatile bool* stop_;
    std::thread        thread_;
    std::atomic<bool>  started_{false};
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_POLL_LOOP_H
