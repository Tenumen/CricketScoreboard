// debug_server.h — phone-accessible HTTP debug page served from the Pi.
// Protects every endpoint with HTTP Basic Auth (admin + config password).
// Runs on its own thread; safe to construct only if password is non-empty.

#ifndef RASPSCOREBOARD24_DEBUG_SERVER_H
#define RASPSCOREBOARD24_DEBUG_SERVER_H

#include <atomic>
#include <memory>
#include <string>
#include <thread>

#include "match_state.h"

namespace httplib { class Server; }

namespace cricketboard {

class DebugServer {
public:
    // `state` and the underlying string storage must outlive the server.
    // `password` must be non-empty — callers are responsible for the
    // fail-closed "no password = no server" policy.
    // `repo_dir` is the on-Pi git checkout used by /api/version and the
    // update/rollback scripts; `scripts_dir` is the directory containing
    // update.sh and rollback.sh.
    DebugServer(const SharedMatchState* state,
                std::string password,
                int port,
                std::string repo_dir,
                std::string scripts_dir);
    ~DebugServer();

    DebugServer(const DebugServer&) = delete;
    DebugServer& operator=(const DebugServer&) = delete;

    void start();   // spawns the thread; returns immediately
    void stop();    // signals server, joins thread

private:
    void run();

    const SharedMatchState*       state_;
    std::string                   password_;
    int                           port_;
    std::string                   repo_dir_;
    std::string                   scripts_dir_;
    std::unique_ptr<httplib::Server> server_;
    std::thread                   thread_;
    std::atomic<bool>             started_{false};
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_DEBUG_SERVER_H
