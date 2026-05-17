#include "frame_emitter.h"

#include <curl/curl.h>

#include <chrono>
#include <cstdio>
#include <cstring>

namespace cricketboard {

namespace {

std::string join_url(const std::string &base, const char *path) {
    if (!base.empty() && base.back() == '/') return base + (path[0] == '/' ? path + 1 : path);
    return base + path;
}

}  // namespace

FrameEmitter::FrameEmitter(std::string base_url, int width, int height,
                           bool send_on_change_only)
    : endpoint_url_(join_url(base_url, "/api/sim/frame")),
      width_(width), height_(height),
      send_on_change_only_(send_on_change_only) {
    // libcurl global init must happen exactly once; play_cricket_client may
    // also init it. curl_global_init is reference-counted and thread-safe-ish
    // when called from main before any other threads.
    static int dummy = []{
        curl_global_init(CURL_GLOBAL_DEFAULT);
        return 0;
    }(); (void)dummy;
    thread_ = std::thread([this]{ run(); });
    std::fprintf(stderr, "FrameEmitter: POSTing to %s\n", endpoint_url_.c_str());
}

FrameEmitter::~FrameEmitter() {
    {
        std::lock_guard<std::mutex> lk(mu_);
        quit_ = true;
        cv_.notify_all();
    }
    if (thread_.joinable()) thread_.join();
}

void FrameEmitter::queue_frame(const std::vector<uint8_t> &bytes) {
    {
        std::lock_guard<std::mutex> lk(mu_);
        if (send_on_change_only_ && bytes == last_sent_) return;
        pending_ = bytes;     // copy; drop any older queued frame
    }
    cv_.notify_one();
}

void FrameEmitter::run() {
    CURL *curl = curl_easy_init();
    if (!curl) {
        std::fprintf(stderr, "FrameEmitter: curl_easy_init failed; thread exiting\n");
        return;
    }
    curl_easy_setopt(curl, CURLOPT_URL,        endpoint_url_.c_str());
    curl_easy_setopt(curl, CURLOPT_POST,       1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT,    5L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT,  "raspscoreboard24-sim/0.1");

    while (true) {
        std::vector<uint8_t> frame;
        uint64_t this_frame_no = 0;
        {
            std::unique_lock<std::mutex> lk(mu_);
            cv_.wait(lk, [this]{ return quit_ || !pending_.empty(); });
            if (quit_) break;
            frame = std::move(pending_);
            pending_.clear();
            this_frame_no = ++frame_no_;
        }
        if (frame.size() != size_t(width_) * height_ * 3) {
            std::fprintf(stderr, "FrameEmitter: bad frame size %zu (expected %d)\n",
                         frame.size(), width_ * height_ * 3);
            continue;
        }

        // Build headers per request — width/height/frame_no.
        struct curl_slist *headers = nullptr;
        char buf[64];
        headers = curl_slist_append(headers, "Content-Type: application/octet-stream");
        std::snprintf(buf, sizeof(buf), "X-Frame-Width: %d", width_);
        headers = curl_slist_append(headers, buf);
        std::snprintf(buf, sizeof(buf), "X-Frame-Height: %d", height_);
        headers = curl_slist_append(headers, buf);
        std::snprintf(buf, sizeof(buf), "X-Frame-Number: %llu",
                      static_cast<unsigned long long>(this_frame_no));
        headers = curl_slist_append(headers, buf);
        const auto ts_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        std::snprintf(buf, sizeof(buf), "X-Frame-Timestamp-Ms: %lld",
                      static_cast<long long>(ts_ms));
        headers = curl_slist_append(headers, buf);

        curl_easy_setopt(curl, CURLOPT_HTTPHEADER,    headers);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS,    frame.data());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(frame.size()));

        const CURLcode rc = curl_easy_perform(curl);
        long status = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);

        if (rc != CURLE_OK || status < 200 || status >= 300) {
            const int n = consecutive_errors_.fetch_add(1) + 1;
            if (n == 1 || n % 30 == 0) {
                std::fprintf(stderr, "FrameEmitter: send failed (rc=%d, http=%ld, #=%d): %s\n",
                             rc, status, n, rc != CURLE_OK ? curl_easy_strerror(rc) : "");
            }
        } else {
            if (consecutive_errors_.exchange(0) >= 1) {
                std::fprintf(stderr, "FrameEmitter: recovered.\n");
            }
            std::lock_guard<std::mutex> lk(mu_);
            last_sent_ = std::move(frame);
        }
        curl_slist_free_all(headers);
    }
    curl_easy_cleanup(curl);
}

}  // namespace cricketboard
