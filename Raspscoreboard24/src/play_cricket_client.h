// play_cricket_client.h — thin wrapper around libcurl for the two endpoints we
// poll, plus a mock-mode file reader. All functions are blocking and meant to
// be called from the poll thread only.

#ifndef RASPSCOREBOARD24_PLAY_CRICKET_CLIENT_H
#define RASPSCOREBOARD24_PLAY_CRICKET_CLIENT_H

#include <string>

namespace cricketboard {

struct HttpResult {
    bool ok = false;
    long http_status = 0;        // 200 on success; 0 when transport itself failed
    std::string body;            // response body on success
    std::string error;           // human-readable transport / API error otherwise
};

// GET <base_url>/api/v2/match_detail.json?match_id=<id>&api_token=<token>
// `base_url` empty => default http://play-cricket.com. Pass a different
// base (e.g. http://dev-box:5050) to talk to mock_playcricket.
HttpResult FetchMatchDetail(int match_id, const std::string& api_token,
                            const std::string& base_url = "");

// GET <base_url>/api/v2/result_summary.json?site_id=<id>&from_match_date=<d>&end_match_date=<d>&api_token=<token>
// `today_ddmmyyyy` should be the UK-format date string "DD/MM/YYYY".
HttpResult FetchResultSummary(int site_id,
                              const std::string& today_ddmmyyyy,
                              const std::string& api_token,
                              const std::string& base_url = "");

// Read a file as a JSON body — used in mock mode in place of the HTTP calls.
HttpResult ReadMockFile(const std::string& path);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_PLAY_CRICKET_CLIENT_H
