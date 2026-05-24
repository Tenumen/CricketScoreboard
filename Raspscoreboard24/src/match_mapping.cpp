#include "match_mapping.h"

#include <algorithm>
#include <cctype>
#include <exception>
#include <string>
#include <vector>

#include "json.hpp"

namespace cricketboard {

namespace {

using json = nlohmann::json;

// Play-Cricket returns every numeric field as a string ("245", "0", ""). These
// helpers tolerate strings, ints, and missing fields without throwing.
int ToInt(const json& v) {
    if (v.is_number_integer()) return v.get<int>();
    if (v.is_number_float())   return static_cast<int>(v.get<double>());
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        if (s.empty()) return 0;
        try { return std::stoi(s); } catch (...) { return 0; }
    }
    return 0;
}

std::string ToStr(const json& v) {
    if (v.is_string())          return v.get<std::string>();
    if (v.is_number_integer())  return std::to_string(v.get<long long>());
    if (v.is_number_unsigned()) return std::to_string(v.get<unsigned long long>());
    if (v.is_number_float())    return std::to_string(v.get<double>());
    if (v.is_null())            return std::string();
    return std::string();
}

bool ToBool(const json& v) {
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number())  return v.get<double>() != 0.0;
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        return s == "true" || s == "1";
    }
    return false;
}

uint64_t ToU64(const json& v) {
    if (v.is_number_integer())  return static_cast<uint64_t>(v.get<long long>());
    if (v.is_number_unsigned()) return v.get<uint64_t>();
    if (v.is_number_float())    return static_cast<uint64_t>(v.get<double>());
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        if (s.empty()) return 0;
        try { return std::stoull(s); } catch (...) { return 0; }
    }
    return 0;
}

const json& Field(const json& obj, const char* key) {
    static const json kNull = json();
    auto it = obj.find(key);
    return it == obj.end() ? kNull : *it;
}

std::string LowerTrim(std::string s) {
    auto not_space = [](unsigned char c){ return !std::isspace(c); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
    s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

bool BatterStillAtCrease(const std::string& how_out_raw) {
    const std::string h = LowerTrim(how_out_raw);
    return h.empty() || h == "not out";
}

bool InningsHasActivity(const json& inn) {
    return ToInt(Field(inn, "runs"))    > 0 ||
           ToInt(Field(inn, "wickets")) > 0 ||
           !ToStr(Field(inn, "overs")).empty();
}

InningsSummary BuildSummary(const json& inn) {
    InningsSummary s;
    s.team_name = ToStr(Field(inn, "team_batting_name"));
    s.runs      = ToInt(Field(inn, "runs"));
    s.wkts      = ToInt(Field(inn, "wickets"));
    s.overs     = ToStr(Field(inn, "overs"));
    s.valid     = !s.team_name.empty();
    return s;
}

}  // namespace

MapResult MapMatchDetail(const std::string& json_body, int our_club_id) {
    MapResult result;

    json root;
    try {
        root = json::parse(json_body);
    } catch (const std::exception& e) {
        result.error = std::string("JSON parse failed: ") + e.what();
        return result;
    }

    const json& details = Field(root, "match_details");
    if (!details.is_array() || details.empty()) {
        result.error = "match_details array missing or empty";
        return result;
    }
    const json& m = details.front();

    MatchState& st = result.state;
    st.home_club_name = ToStr(Field(m, "home_club_name"));
    st.home_team_name = ToStr(Field(m, "home_team_name"));
    st.away_club_name = ToStr(Field(m, "away_club_name"));
    st.away_team_name = ToStr(Field(m, "away_team_name"));
    st.home_team      = st.home_team_name;
    st.opponent       = st.away_team_name;

    // Per-ball / per-wicket counters. Absent on un-upgraded bridges -> 0.
    {
        const json& le = Field(m, "last_event");
        if (le.is_object()) {
            st.last_ball_id        = ToU64(Field(le, "ball_id"));
            st.last_ball_runs      = ToInt(Field(le, "ball_runs"));
            st.last_ball_is_wicket = ToBool(Field(le, "ball_is_wicket"));
            st.last_wicket_id      = ToU64(Field(le, "wicket_id"));
        }
    }

    // Phase classification.
    const std::string result_field      = ToStr(Field(m, "result"));
    const std::string result_desc       = ToStr(Field(m, "result_description"));
    const bool        has_result        = !result_field.empty() && !result_desc.empty();

    // Sort innings by innings_number so [0] = 1st innings, [1] = 2nd.
    std::vector<json> innings_sorted;
    {
        const json& innings = Field(m, "innings");
        if (innings.is_array()) {
            for (const auto& inn : innings) innings_sorted.push_back(inn);
            std::sort(innings_sorted.begin(), innings_sorted.end(),
                      [](const json& a, const json& b){
                          return ToInt(Field(a, "innings_number")) <
                                 ToInt(Field(b, "innings_number"));
                      });
        }
    }
    const bool any_innings_with_activity =
        std::any_of(innings_sorted.begin(), innings_sorted.end(), InningsHasActivity);

    if (has_result) {
        st.phase = MatchPhase::POST_MATCH;
    } else if (!any_innings_with_activity) {
        st.phase = MatchPhase::PRE_MATCH;
    } else {
        st.phase = MatchPhase::IN_MATCH;
    }

    // POST_MATCH fields populated whenever we have completed innings to summarise.
    st.result_description = result_desc;
    if (innings_sorted.size() >= 1) st.inn1 = BuildSummary(innings_sorted[0]);
    if (innings_sorted.size() >= 2) st.inn2 = BuildSummary(innings_sorted[1]);

    if (st.phase != MatchPhase::IN_MATCH) {
        result.ok = true;
        return result;
    }

    // IN_MATCH path: pick the current innings (highest-numbered with any activity).
    const json* current = nullptr;
    const json* previous = nullptr;
    for (auto it = innings_sorted.rbegin(); it != innings_sorted.rend(); ++it) {
        if (InningsHasActivity(*it)) {
            current = &*it;
            ++it;
            if (it != innings_sorted.rend()) previous = &*it;
            break;
        }
    }
    if (!current) {
        // Defensive — shouldn't reach here given the phase check above.
        st.phase = MatchPhase::PRE_MATCH;
        result.ok = true;
        return result;
    }

    st.runs         = ToInt(Field(*current, "runs"));
    st.wkts         = ToInt(Field(*current, "wickets"));
    st.overs        = ToStr(Field(*current, "overs"));
    st.total_extras = ToInt(Field(*current, "total_extras"));

    // Chasing logic. We are chasing iff a previous innings exists and was
    // batted by the OTHER team (not us). `our_club_id` resolves who 'we' are.
    const int home_club_id    = ToInt(Field(m, "home_club_id"));
    const int away_club_id    = ToInt(Field(m, "away_club_id"));
    const bool we_are_home    = (our_club_id != 0 && our_club_id == home_club_id);
    const bool we_are_away    = (our_club_id != 0 && our_club_id == away_club_id);
    (void)we_are_away;  // currently only home/away orientation is informational

    if (previous) {
        const int prev_runs = ToInt(Field(*previous, "runs"));
        const int prev_wkts = ToInt(Field(*previous, "wickets"));
        const int prev_team_id = ToInt(Field(*previous, "team_batting_id"));

        // Inferring "us batting": if we have a club configured, infer from
        // team_batting_id matching home/away club_id according to who we are.
        // If we_are_home and previous innings was batted by the away team
        // (or vice versa), the current innings is our chase.
        bool we_are_batting_now = true;
        if (our_club_id != 0) {
            const int cur_team_id = ToInt(Field(*current, "team_batting_id"));
            const int our_team_id_in_match = we_are_home
                ? ToInt(Field(m, "home_team_id"))
                : ToInt(Field(m, "away_team_id"));
            if (our_team_id_in_match != 0) {
                we_are_batting_now = (cur_team_id == our_team_id_in_match);
            }
            (void)prev_team_id;
        }
        st.chasing       = we_are_batting_now && prev_runs > 0;
        st.last_inn_runs = st.chasing ? prev_runs : 0;
        st.last_inn_wkts = st.chasing ? prev_wkts : 0;

        const int revised_target = ToInt(Field(*current, "revised_target_runs"));
        if (revised_target > 0) {
            st.target = revised_target;
        } else if (st.chasing) {
            st.target = prev_runs + 1;
        }
    }

    // Pick the up-to-two not-out batters in the current innings, ordered by
    // batting position. See plan §"Determining the current batters".
    {
        const json& bat = Field(*current, "bat");
        if (bat.is_array()) {
            struct Active { int position; std::string name; int runs; };
            std::vector<Active> active;
            active.reserve(2);

            for (const auto& b : bat) {
                if (!BatterStillAtCrease(ToStr(Field(b, "how_out")))) continue;
                active.push_back({
                    ToInt(Field(b, "position")),
                    ToStr(Field(b, "batsman_name")),
                    ToInt(Field(b, "runs")),
                });
            }
            std::sort(active.begin(), active.end(),
                      [](const Active& a, const Active& b){ return a.position < b.position; });
            if (active.size() >= 1) {
                st.bat1_name  = active[0].name;
                st.bat1_score = active[0].runs;
            }
            if (active.size() >= 2) {
                st.bat2_name  = active[1].name;
                st.bat2_score = active[1].runs;
            }
        }
    }

    result.ok = true;
    return result;
}

}  // namespace cricketboard
