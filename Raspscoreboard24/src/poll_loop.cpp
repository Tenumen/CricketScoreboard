#include "poll_loop.h"

#include <chrono>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>

#include "json.hpp"
#include "match_mapping.h"
#include "play_cricket_client.h"

namespace cricketboard {

namespace {

using json = nlohmann::json;

std::string TodayDdMmYyyy() {
    const std::time_t now = std::time(nullptr);
    std::tm tm{};
    localtime_r(&now, &tm);
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%02d/%02d/%04d",
                  tm.tm_mday, tm.tm_mon + 1, tm.tm_year + 1900);
    return buf;
}

// Best-effort: look at a result_summary response and pull the first match id.
// The endpoint returns matches scheduled for the date range; for our use we
// expect at most one fixture per day per club.
bool PickMatchIdFromResultSummary(const std::string& body, int* out_match_id) {
    try {
        const json root = json::parse(body);
        auto it = root.find("result_summary");
        if (it == root.end() || !it->is_array() || it->empty()) return false;
        const json& first = it->front();
        auto id_it = first.find("id");
        if (id_it == first.end()) return false;
        if (id_it->is_number_integer()) {
            *out_match_id = id_it->get<int>();
            return true;
        }
        if (id_it->is_string()) {
            try { *out_match_id = std::stoi(id_it->get<std::string>()); return true; }
            catch (...) { return false; }
        }
        return false;
    } catch (...) {
        return false;
    }
}

// Interruptible sleep: returns false if `stop` flipped during the wait.
bool SleepFor(int seconds, const volatile bool* stop) {
    for (int i = 0; i < seconds; ++i) {
        if (*stop) return false;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    return !*stop;
}

}  // namespace

PollConfig LoadConfig(const std::string& path) {
    PollConfig cfg;
    std::ifstream in(path);
    if (!in) {
        std::fprintf(stderr,
                     "Config '%s' not found — using defaults (mock_mode=true, path='%s').\n",
                     path.c_str(), cfg.mock_data_path.c_str());
        return cfg;
    }
    try {
        std::ostringstream buf; buf << in.rdbuf();
        const json j = json::parse(buf.str());
        if (j.contains("api_token")            && j["api_token"].is_string())   cfg.api_token           = j["api_token"].get<std::string>();
        if (j.contains("club_site_id")         && j["club_site_id"].is_number()) cfg.club_site_id       = j["club_site_id"].get<int>();
        if (j.contains("poll_interval_seconds")&& j["poll_interval_seconds"].is_number()) cfg.poll_interval_secs = j["poll_interval_seconds"].get<int>();
        if (j.contains("mock_mode")            && j["mock_mode"].is_boolean()) cfg.mock_mode             = j["mock_mode"].get<bool>();
        if (j.contains("mock_data_path")       && j["mock_data_path"].is_string()) cfg.mock_data_path    = j["mock_data_path"].get<std::string>();
        if (j.contains("debug_server_enabled") && j["debug_server_enabled"].is_boolean()) cfg.debug_server_enabled = j["debug_server_enabled"].get<bool>();
        if (j.contains("debug_server_port")    && j["debug_server_port"].is_number())    cfg.debug_server_port    = j["debug_server_port"].get<int>();
        if (j.contains("debug_server_password")&& j["debug_server_password"].is_string()) cfg.debug_server_password = j["debug_server_password"].get<std::string>();
        if (j.contains("api_base_url")         && j["api_base_url"].is_string())          cfg.api_base_url          = j["api_base_url"].get<std::string>();
        if (j.contains("sim_endpoint")         && j["sim_endpoint"].is_string())          cfg.sim_endpoint          = j["sim_endpoint"].get<std::string>();
        if (j.contains("sim_endpoint_send_on_change_only") && j["sim_endpoint_send_on_change_only"].is_boolean())
            cfg.sim_endpoint_send_on_change_only = j["sim_endpoint_send_on_change_only"].get<bool>();
        if (j.contains("repo_dir")    && j["repo_dir"].is_string())    cfg.repo_dir    = j["repo_dir"].get<std::string>();
        if (j.contains("scripts_dir") && j["scripts_dir"].is_string()) cfg.scripts_dir = j["scripts_dir"].get<std::string>();
        if (j.contains("display_pwm_bits")              && j["display_pwm_bits"].is_number())              cfg.display_pwm_bits              = j["display_pwm_bits"].get<int>();
        if (j.contains("display_pwm_dither_bits")       && j["display_pwm_dither_bits"].is_number())       cfg.display_pwm_dither_bits       = j["display_pwm_dither_bits"].get<int>();
        if (j.contains("display_limit_refresh_rate_hz") && j["display_limit_refresh_rate_hz"].is_number()) cfg.display_limit_refresh_rate_hz = j["display_limit_refresh_rate_hz"].get<int>();
        if (j.contains("display_brightness")            && j["display_brightness"].is_number())            cfg.display_brightness            = j["display_brightness"].get<int>();
        if (j.contains("display_gpio_slowdown")         && j["display_gpio_slowdown"].is_number())         cfg.display_gpio_slowdown         = j["display_gpio_slowdown"].get<int>();
        if (j.contains("display_show_refresh_rate")     && j["display_show_refresh_rate"].is_boolean())    cfg.display_show_refresh_rate     = j["display_show_refresh_rate"].get<bool>();
    } catch (const std::exception& e) {
        std::fprintf(stderr, "Config '%s' parse error: %s — using defaults.\n", path.c_str(), e.what());
    }
    // Floor lowered from 5s -> 1s so the sim can poll fast while a user is
    // scoring; real-Pi configs keep their 30s explicit value.
    if (cfg.poll_interval_secs < 1) cfg.poll_interval_secs = 1;
    // Defensive clamps so a fat-fingered config can't produce an invalid
    // matrix init (the library asserts on out-of-range pwm_bits/brightness).
    if (cfg.display_brightness < 1)   cfg.display_brightness = 1;
    if (cfg.display_brightness > 100) cfg.display_brightness = 100;
    if (cfg.display_pwm_bits   < 1)   cfg.display_pwm_bits   = 1;
    if (cfg.display_pwm_bits   > 11)  cfg.display_pwm_bits   = 11;
    if (cfg.display_pwm_dither_bits < 0) cfg.display_pwm_dither_bits = 0;
    return cfg;
}

PollLoop::PollLoop(PollConfig cfg, SharedMatchState* state, const volatile bool* stop)
    : cfg_(std::move(cfg)), state_(state), stop_(stop) {}

PollLoop::~PollLoop() {
    if (thread_.joinable()) thread_.join();
}

void PollLoop::start() {
    if (started_.exchange(true)) return;
    thread_ = std::thread([this]{ run(); });
}

void PollLoop::join() {
    if (thread_.joinable()) thread_.join();
}

void PollLoop::run() {
    std::fprintf(stderr, "Poll loop started: mock_mode=%s, interval=%ds\n",
                 cfg_.mock_mode ? "true" : "false", cfg_.poll_interval_secs);

    int match_id = 0;
    int backoff  = cfg_.poll_interval_secs;
    const int max_backoff = 300;

    while (!*stop_) {
        HttpResult http;

        if (cfg_.mock_mode) {
            http = ReadMockFile(cfg_.mock_data_path);
        } else {
            // Discover match_id once per fresh run (and re-discover after errors).
            if (match_id == 0) {
                const HttpResult disco = FetchResultSummary(
                    cfg_.club_site_id, TodayDdMmYyyy(), cfg_.api_token, cfg_.api_base_url);
                if (!disco.ok) {
                    std::fprintf(stderr, "result_summary failed: %s — backing off %ds\n",
                                 disco.error.c_str(), backoff);
                } else if (!PickMatchIdFromResultSummary(disco.body, &match_id)) {
                    // No match today: hold phase = NO_MATCH and try again later.
                    MatchState empty;
                    empty.phase = MatchPhase::NO_MATCH;
                    state_->update(empty);
                    if (!SleepFor(cfg_.poll_interval_secs, stop_)) break;
                    continue;
                } else {
                    std::fprintf(stderr, "Discovered match_id=%d for today.\n", match_id);
                    backoff = cfg_.poll_interval_secs;
                }
            }
            if (match_id != 0) {
                http = FetchMatchDetail(match_id, cfg_.api_token, cfg_.api_base_url);
            }
        }

        if (!http.ok) {
            std::fprintf(stderr, "fetch failed: %s — backing off %ds\n",
                         http.error.c_str(), backoff);
            if (!SleepFor(backoff, stop_)) break;
            backoff = std::min(backoff * 2, max_backoff);
            match_id = 0;  // force re-discovery on next iter when live
            continue;
        }
        backoff = cfg_.poll_interval_secs;

        const MapResult mr = MapMatchDetail(http.body, cfg_.club_site_id);
        if (!mr.ok) {
            std::fprintf(stderr, "mapping failed: %s\n", mr.error.c_str());
            if (!SleepFor(cfg_.poll_interval_secs, stop_)) break;
            continue;
        }
        state_->update(mr.state);

        if (!SleepFor(cfg_.poll_interval_secs, stop_)) break;
    }

    std::fprintf(stderr, "Poll loop exiting.\n");
}

}  // namespace cricketboard
