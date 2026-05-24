#include "effects/event_detect.h"

namespace cricketboard {

Interlude DetectEvent(const MatchState& prev, const MatchState& curr) {
    // Phase transition into POST_MATCH wins outright -- no balls bowled in
    // POST_MATCH, so the other branches can't fire.
    if (curr.phase == MatchPhase::POST_MATCH &&
        prev.phase != MatchPhase::POST_MATCH) {
        return Interlude::PostMatchFireworks;
    }
    if (curr.phase == MatchPhase::POST_MATCH) {
        return Interlude::None;
    }

    if (curr.last_wicket_id > prev.last_wicket_id) {
        return Interlude::Wicket;
    }
    if (curr.last_ball_id > prev.last_ball_id) {
        // Six checked before Four; the BLE COV path encodes runs as a single
        // digit, so a "6" delivery can never also be a "4".
        if (curr.last_ball_runs == 6) return Interlude::Six;
        if (curr.last_ball_runs == 4) return Interlude::Four;
    }
    return Interlude::None;
}

}  // namespace cricketboard
