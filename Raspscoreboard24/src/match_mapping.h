// match_mapping.h — convert a Play-Cricket match_detail.json body into a
// MatchState. Pure function: no I/O, no logging side effects, no threading.

#ifndef RASPSCOREBOARD24_MATCH_MAPPING_H
#define RASPSCOREBOARD24_MATCH_MAPPING_H

#include <string>

#include "match_state.h"

namespace cricketboard {

struct MapResult {
    bool ok = false;
    std::string error;   // populated when ok = false; empty otherwise
    MatchState  state;   // populated when ok = true; phase encodes what we found
};

// Parse `json_body` (the raw response body of /api/v2/match_detail.json) and
// return a MatchState. Phase is derived from the JSON content alone — the
// caller is responsible for setting phase = NO_MATCH when discovery itself
// failed (i.e. before this function is reached).
//
// `our_club_id` is the configured club's site_id. It's used purely for
// orientation (so we know whether we're the home or away club); the rendered
// names don't change based on this.
MapResult MapMatchDetail(const std::string& json_body, int our_club_id);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_MATCH_MAPPING_H
