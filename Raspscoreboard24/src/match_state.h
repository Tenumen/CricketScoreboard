// match_state.h — live match snapshot shared between the polling thread and
// the render thread. One struct holds every field the scoreboard might want to
// display; the renderer picks which subset to draw based on `phase`.

#ifndef RASPSCOREBOARD24_MATCH_STATE_H
#define RASPSCOREBOARD24_MATCH_STATE_H

#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <string>

namespace cricketboard {

enum class MatchPhase {
    NO_MATCH,    // no fixture today, or discovery is still pending
    PRE_MATCH,   // fixture found but no balls bowled yet
    IN_MATCH,    // at least one innings has values, result not yet decided
    POST_MATCH,  // result populated by scorer
};

struct InningsSummary {
    std::string team_name;
    int runs = 0;
    int wkts = 0;
    std::string overs;   // verbatim from API, e.g. "37.4"
    bool valid = false;
};

// Operator "Innings finished" summary screen, frozen by the bridge at the
// interval and shown over the live board until the next innings resumes. Top
// two = highest scorers of the innings; has_extras is false in pairs cricket
// (extras cannot be derived there) so the renderer omits the Extras line.
struct InningsSummaryScreen {
    bool active = false;
    std::string team_name;
    int runs = 0;
    int wkts = 0;
    bool has_extras = false;
    int  extras = 0;
    std::string overs;
    std::string bat1_name;
    int bat1_score = 0;
    std::string bat2_name;
    int bat2_score = 0;
};

struct MatchState {
    MatchPhase phase = MatchPhase::NO_MATCH;

    // Always populated when phase >= PRE_MATCH. Used by the pre-match splash
    // and as the headline names on the main scoreboard.
    std::string home_club_name;
    std::string home_team_name;
    std::string away_club_name;
    std::string away_team_name;

    // IN_MATCH fields.
    std::string home_team;   // convenience copy of home_team_name for the existing layout
    std::string opponent;    // convenience copy of away_team_name
    bool chasing = false;
    int  target = 0;
    int  runs = 0;           // team total — INCLUDES extras
    int  wkts = 0;
    std::string overs;       // e.g. "12.3"
    std::string bat1_name;
    int  bat1_score = 0;
    std::string bat2_name;
    int  bat2_score = 0;
    int  on_strike = 0;      // 0 = unknown; reserved for a future API field
    int  last_inn_runs = 0;
    int  last_inn_wkts = 0;
    int  total_extras = 0;   // unused on the display today; trivial to surface later

    // POST_MATCH fields.
    std::string result_description;
    InningsSummary inn1;
    InningsSummary inn2;

    // Per-ball / per-wicket event counters mirrored from the bridge.
    // Monotonic; consumed by the renderer's event_detect to fire splashes.
    // Safe defaults so a bridge that doesn't publish last_event still works.
    uint64_t last_ball_id        = 0;
    int      last_ball_runs      = 0;
    bool     last_ball_is_wicket = false;
    uint64_t last_wicket_id      = 0;

    // Operator "Innings finished" frozen summary. When active, the renderer
    // shows it instead of the live IN_MATCH board.
    InningsSummaryScreen innings_summary;

    // Bumped on every successful update from the poll thread. The render
    // thread compares the snapshot it last drew against the live value to
    // decide whether to redraw.
    uint64_t generation = 0;
};

// Content equality, ignoring `generation`. Used to suppress redundant updates
// (and the redraw they trigger) when a poll returns data identical to the last.
inline bool operator==(const InningsSummary& a, const InningsSummary& b) {
    return a.team_name == b.team_name && a.runs == b.runs && a.wkts == b.wkts &&
           a.overs == b.overs && a.valid == b.valid;
}

inline bool operator==(const InningsSummaryScreen& a, const InningsSummaryScreen& b) {
    return a.active == b.active && a.team_name == b.team_name &&
           a.runs == b.runs && a.wkts == b.wkts &&
           a.has_extras == b.has_extras && a.extras == b.extras &&
           a.overs == b.overs &&
           a.bat1_name == b.bat1_name && a.bat1_score == b.bat1_score &&
           a.bat2_name == b.bat2_name && a.bat2_score == b.bat2_score;
}

// True when every displayable field of `a` and `b` matches. Compares ALL fields
// except `generation` — including the per-ball/per-wicket event counters, so a
// genuine ball or wicket is never deduped away and splash detection still fires.
inline bool SameContent(const MatchState& a, const MatchState& b) {
    return a.phase == b.phase &&
           a.home_club_name == b.home_club_name &&
           a.home_team_name == b.home_team_name &&
           a.away_club_name == b.away_club_name &&
           a.away_team_name == b.away_team_name &&
           a.home_team == b.home_team &&
           a.opponent == b.opponent &&
           a.chasing == b.chasing &&
           a.target == b.target &&
           a.runs == b.runs &&
           a.wkts == b.wkts &&
           a.overs == b.overs &&
           a.bat1_name == b.bat1_name &&
           a.bat1_score == b.bat1_score &&
           a.bat2_name == b.bat2_name &&
           a.bat2_score == b.bat2_score &&
           a.on_strike == b.on_strike &&
           a.last_inn_runs == b.last_inn_runs &&
           a.last_inn_wkts == b.last_inn_wkts &&
           a.total_extras == b.total_extras &&
           a.result_description == b.result_description &&
           a.inn1 == b.inn1 &&
           a.inn2 == b.inn2 &&
           a.last_ball_id == b.last_ball_id &&
           a.last_ball_runs == b.last_ball_runs &&
           a.last_ball_is_wicket == b.last_ball_is_wicket &&
           a.last_wicket_id == b.last_wicket_id &&
           a.innings_summary == b.innings_summary;
}

// Thread-safe holder. The poll thread calls update(), which copies in the new
// state, bumps generation, and notifies waiters. The render thread waits on
// the condvar (with a timeout for SIGTERM responsiveness) and then copies the
// state out under the lock.
class SharedMatchState {
public:
    // Replace the held state with `s` (its generation field is overwritten
    // with a freshly-bumped value) and wake any waiter.
    void update(const MatchState& s) {
        std::lock_guard<std::mutex> lk(mutex_);
        if (SameContent(state_, s)) return;   // identical data -> no redraw
        state_ = s;
        state_.generation = ++generation_counter_;
        cv_.notify_all();
    }

    // Read-only snapshot. Cheap to call from the render loop.
    MatchState snapshot() const {
        std::lock_guard<std::mutex> lk(mutex_);
        return state_;
    }

    // Block until generation moves past `since` or `timeout` elapses or `stop`
    // becomes true. Returns the current state snapshot either way; the caller
    // can compare its `generation` against `since` to know whether anything
    // actually changed.
    template <class Rep, class Period>
    MatchState wait_for_update(uint64_t since,
                               std::chrono::duration<Rep, Period> timeout,
                               const volatile bool& stop) const {
        std::unique_lock<std::mutex> lk(mutex_);
        cv_.wait_for(lk, timeout, [&] {
            return state_.generation != since || stop;
        });
        return state_;
    }

private:
    mutable std::mutex mutex_;
    mutable std::condition_variable cv_;
    MatchState state_;
    uint64_t generation_counter_ = 0;
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_MATCH_STATE_H
