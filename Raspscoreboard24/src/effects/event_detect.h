// event_detect.h -- map a (prev, curr) MatchState pair to the splash that
// should fire. Pure; no I/O, no globals. Cancel-and-replace semantics live
// in the caller (the render loop in main.cpp).

#ifndef RASPSCOREBOARD24_EFFECTS_EVENT_DETECT_H
#define RASPSCOREBOARD24_EFFECTS_EVENT_DETECT_H

#include "match_state.h"

namespace cricketboard {

enum class Interlude {
    None,
    Wicket,
    Four,
    Six,
    PostMatchFireworks,
};

Interlude DetectEvent(const MatchState& prev, const MatchState& curr);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_EFFECTS_EVENT_DETECT_H
