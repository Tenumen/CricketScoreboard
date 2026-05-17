#include "play_cricket_client.h"

#include <curl/curl.h>

#include <cstdio>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>

namespace cricketboard {

namespace {

// libcurl global init is required exactly once per process. Guard it.
void EnsureCurlGlobalInit() {
    static std::once_flag init_once;
    std::call_once(init_once, []{ curl_global_init(CURL_GLOBAL_DEFAULT); });
}

size_t WriteToString(char* ptr, size_t size, size_t nmemb, void* userdata) {
    const size_t bytes = size * nmemb;
    auto* out = static_cast<std::string*>(userdata);
    out->append(ptr, bytes);
    return bytes;
}

HttpResult DoGet(const std::string& url) {
    EnsureCurlGlobalInit();

    HttpResult r;
    CURL* curl = curl_easy_init();
    if (!curl) {
        r.error = "curl_easy_init failed";
        return r;
    }

    curl_easy_setopt(curl, CURLOPT_URL,             url.c_str());
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION,  1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT,         15L);   // total seconds
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT,  5L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT,       "raspscoreboard24/0.1");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION,   WriteToString);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA,       &r.body);

    const CURLcode rc = curl_easy_perform(curl);
    if (rc != CURLE_OK) {
        r.error = std::string("curl: ") + curl_easy_strerror(rc);
        curl_easy_cleanup(curl);
        return r;
    }
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &r.http_status);
    curl_easy_cleanup(curl);

    if (r.http_status < 200 || r.http_status >= 300) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "HTTP %ld", r.http_status);
        r.error = buf;
        return r;
    }
    r.ok = true;
    return r;
}

std::string UrlEncode(const std::string& s) {
    EnsureCurlGlobalInit();
    char* enc = curl_easy_escape(nullptr, s.c_str(), static_cast<int>(s.size()));
    std::string out = enc ? std::string(enc) : std::string();
    if (enc) curl_free(enc);
    return out;
}

std::string ResolveBase(const std::string& base_url) {
    if (base_url.empty()) return "http://play-cricket.com";
    if (!base_url.empty() && base_url.back() == '/')
        return base_url.substr(0, base_url.size() - 1);
    return base_url;
}

}  // namespace

HttpResult FetchMatchDetail(int match_id, const std::string& api_token,
                            const std::string& base_url) {
    std::ostringstream u;
    u << ResolveBase(base_url)
      << "/api/v2/match_detail.json"
      << "?match_id=" << match_id
      << "&api_token=" << UrlEncode(api_token);
    return DoGet(u.str());
}

HttpResult FetchResultSummary(int site_id,
                              const std::string& today_ddmmyyyy,
                              const std::string& api_token,
                              const std::string& base_url) {
    std::ostringstream u;
    u << ResolveBase(base_url)
      << "/api/v2/result_summary.json"
      << "?site_id=" << site_id
      << "&from_match_date=" << UrlEncode(today_ddmmyyyy)
      << "&end_match_date="  << UrlEncode(today_ddmmyyyy)
      << "&api_token="       << UrlEncode(api_token);
    return DoGet(u.str());
}

HttpResult ReadMockFile(const std::string& path) {
    HttpResult r;
    std::ifstream in(path);
    if (!in) {
        r.error = "could not open mock file: " + path;
        return r;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    r.body = buf.str();
    r.http_status = 200;
    r.ok = true;
    return r;
}

}  // namespace cricketboard
