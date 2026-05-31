#include "graphics.h"

#include "calibration.h"
#include "debug_server.h"
#include "effects/event_detect.h"
#include "effects/event_splash.h"
#include "effects/fireworks.h"
#include "grid_canvas.h"
#include "match_state.h"
#include "panel_layout.h"
#include "poll_loop.h"
#include "render_backend/backend.h"

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_BMP
#include "stb_image.h"

#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <chrono>
#include <memory>
#include <string>
#include <thread>

using rgb_matrix::Color;
using rgb_matrix::Font;
using rgb_matrix::DrawText;
using cricketboard::CreateDisplay;
using cricketboard::DebugServer;
using cricketboard::DetectEvent;
using cricketboard::DisplayOptions;
using cricketboard::DrawEventSplash;
using cricketboard::Fireworks;
using cricketboard::GridCanvas;
using cricketboard::IDisplay;
using cricketboard::Interlude;
using cricketboard::MatchPhase;
using cricketboard::MatchState;
using cricketboard::PollConfig;
using cricketboard::PollLoop;
using cricketboard::SharedMatchState;
using cricketboard::kPanelPx;

volatile bool interrupt_received = false;
static void InterruptHandler(int /*signo*/) { interrupt_received = true; }

// Strip our own flags out of argv before handing the rest to ParseOptionsFromFlags,
// which would otherwise complain about unrecognised options.
static bool ExtractCalibrateFlag(int *argc, char **argv,
                                 cricketboard::CalibrationMode *mode_out) {
    bool found = false;
    int write = 1;
    for (int read = 1; read < *argc; ++read) {
        const char *a = argv[read];
        if (strcmp(a, "--calibrate") == 0) {
            found = true;
            *mode_out = cricketboard::CalibrationMode::Sequential;
            continue;
        }
        if (strcmp(a, "--calibrate=all") == 0) {
            found = true;
            *mode_out = cricketboard::CalibrationMode::AllAtOnce;
            continue;
        }
        if (strcmp(a, "--calibrate=quads") == 0) {
            found = true;
            *mode_out = cricketboard::CalibrationMode::Quadrants;
            continue;
        }
        argv[write++] = argv[read];
    }
    *argc = write;
    return found;
}

// --demo-splash=<wicket|four|six|fireworks>: bypass live state, force the
// named interlude, exit after a fixed budget. For visual verification on
// the sim backend without a live BLE bridge.
static bool ExtractDemoSplashFlag(int *argc, char **argv, Interlude *out) {
    bool found = false;
    int write = 1;
    for (int read = 1; read < *argc; ++read) {
        const char *a = argv[read];
        if (strncmp(a, "--demo-splash=", 14) == 0) {
            const char *kind = a + 14;
            if      (strcmp(kind, "wicket")    == 0) *out = Interlude::Wicket;
            else if (strcmp(kind, "four")      == 0) *out = Interlude::Four;
            else if (strcmp(kind, "six")       == 0) *out = Interlude::Six;
            else if (strcmp(kind, "fireworks") == 0) *out = Interlude::PostMatchFireworks;
            else {
                fprintf(stderr, "Unknown --demo-splash kind '%s'\n", kind);
                continue;
            }
            found = true;
            continue;
        }
        argv[write++] = argv[read];
    }
    *argc = write;
    return found;
}

// --config <path>  or  --config=<path>
static bool ExtractConfigFlag(int *argc, char **argv, std::string *path_out) {
    bool found = false;
    int write = 1;
    for (int read = 1; read < *argc; ++read) {
        const char *a = argv[read];
        if (strcmp(a, "--config") == 0) {
            if (read + 1 < *argc) {
                *path_out = argv[++read];
                found = true;
            }
            continue;
        }
        if (strncmp(a, "--config=", 9) == 0) {
            *path_out = a + 9;
            found = true;
            continue;
        }
        argv[write++] = argv[read];
    }
    *argc = write;
    return found;
}

// One-shot measurement: load a BDF and print the pixel width of each splash
// label, then exit. Lets us tune the impact-font pixel size without a display.
static int MeasureImpactFont(const char *path) {
    Font f;
    if (!f.LoadFont(path)) {
        fprintf(stderr, "Could not load font '%s'\n", path);
        return 2;
    }
    auto text_width = [&](const char *s) {
        int w = 0;
        for (const char *p = s; *p; ++p) w += f.CharacterWidth(static_cast<uint32_t>(*p));
        return w;
    };
    printf("font:    %s\n", path);
    printf("height:  %d  baseline: %d\n", f.height(), f.baseline());
    printf("Wicket!  %d px\n", text_width("Wicket!"));
    printf("Four!    %d px\n", text_width("Four!"));
    printf("Six!     %d px\n", text_width("Six!"));
    printf("(screen width = 384 px; target Wicket! ∈ [340, 376] px)\n");
    return 0;
}

int main(int argc, char *argv[]) {
    // --measure-impact-font=<path> short-circuits everything: load the font,
    // print text widths for the three splash labels, exit. No display needed.
    for (int i = 1; i < argc; ++i) {
        if (strncmp(argv[i], "--measure-impact-font=", 22) == 0) {
            return MeasureImpactFont(argv[i] + 22);
        }
    }

    cricketboard::CalibrationMode cal_mode = cricketboard::CalibrationMode::Sequential;
    const bool calibrate = ExtractCalibrateFlag(&argc, argv, &cal_mode);

    Interlude demo_splash = Interlude::None;
    const bool demo_mode = ExtractDemoSplashFlag(&argc, argv, &demo_splash);

    std::string config_path = "config.json";
    ExtractConfigFlag(&argc, argv, &config_path);

    // Load config FIRST so the headless backend can pick up sim_endpoint
    // before it constructs its emitter thread. The hub75 backend uses the
    // same options but only reads brightness/pwm/gpio_slowdown from them.
    PollConfig cfg = cricketboard::LoadConfig(config_path);

    DisplayOptions display_opts;
    display_opts.brightness            = 50;
    display_opts.pwm_bits              = 6;
    display_opts.gpio_slowdown         = 3;
    display_opts.limit_refresh_rate_hz = 120;
    display_opts.multiplexing          = 1;
    display_opts.hardware_mapping      = "regular";
    display_opts.sim_endpoint          = cfg.sim_endpoint;
    display_opts.sim_send_on_change_only = cfg.sim_endpoint_send_on_change_only;

    auto display = CreateDisplay(&argc, &argv, display_opts);
    if (!display) {
        return 1;
    }

    signal(SIGTERM, InterruptHandler);
    signal(SIGINT,  InterruptHandler);

    const char *base = "lib/rpi-rgb-led-matrix/fonts/";
    char path[256];

    Font font_label;
    // Standard labels (team names, "vs", batter names, WKTS/OVERS/TO/WIN/LAST/INNS).
    snprintf(path, sizeof(path), "%s10x20.bdf", base);
    if (!font_label.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    Font font_label_big;
    // Prominent left-column labels (RUNS / BAT 1 / BAT 2) — ~50% larger again.
    if (!font_label_big.LoadFont("fonts/liberation-mono-bold-30.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-30.bdf'\n");

    if (calibrate) {
        cricketboard::RunCalibration(display.get(), font_label, cal_mode, &interrupt_received);
        display->clear();
        printf("\nCalibration ended.\n");
        return 0;
    }

    Font font_score;  // large — main runs total only
    if (!font_score.LoadFont("fonts/liberation-mono-bold-60.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-60.bdf'\n");

    Font font_small_num;  // small — every other number on the board
    if (!font_small_num.LoadFont("fonts/liberation-mono-bold-35.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-35.bdf'\n");

    Font font_impact;  // very large — Wicket! / Four! / Six! splashes (~50 px/char)
    if (!font_impact.LoadFont("fonts/liberation-mono-bold-86.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-86.bdf'\n");

    GridCanvas grid(display->current_back_buffer());

    printf("Scoreboard24 running on %dx%d logical canvas (HW %dx%d). Ctrl+C to exit.\n",
           grid.width(), grid.height(),
           display->width(), display->height());

    // ---------- Colour palette (DISPLAY_NOTES_24.md spec) ----------
    Color c_white(255, 255, 255);
    Color c_cyan (100, 200, 255);
    Color c_green(  0, 220,   0);
    Color c_amber(255, 165,   0);
    Color c_red  (255, 110, 110);  // lighter — more luminance for distance readability
    Color c_grey ( 80,  80,  80);

    // ---------- Layout anchors (3 cols × 4 rows of 128×64 cells) ----------
    // Naming is from the AUDIENCE viewpoint. After grid_canvas.cpp was corrected
    // (col 1 = audience-left, not audience-right), low x = audience-left.
    constexpr int kColLeft  = 0,   kColMid   = 128, kColRight = 256, kColW = 128;
    constexpr int kRowA     = 0,   kRowB     = 64,  kRowC     = 128, kRowD = 192;
    (void)kColLeft; (void)kRowA; (void)kRowB; (void)kRowC; (void)kRowD;
    constexpr int kLeftCx   = kColLeft  + kColW / 2;   //  64
    constexpr int kMidCx    = kColMid   + kColW / 2;   // 192
    constexpr int kRightCx  = kColRight + kColW / 2;   // 320

    // ---------- Helpers ----------
    auto text_width = [](const Font &f, const char *s) {
        int w = 0;
        for (const char *p = s; *p; ++p) w += f.CharacterWidth(static_cast<uint32_t>(*p));
        return w;
    };
    auto draw_centered = [&](const Font &f, int cx, int y_baseline,
                             const Color &col, const char *s) {
        int w = text_width(f, s);
        DrawText(&grid, f, cx - w / 2, y_baseline, col, nullptr, s, 0);
    };
    auto draw_left = [&](const Font &f, int x_left, int y_baseline,
                         const Color &col, const char *s) {
        DrawText(&grid, f, x_left, y_baseline, col, nullptr, s, 0);
    };
    // Convert a desired vertical *centre* into a text baseline for that font.
    // Treats baseline()/height() as ascent/descent: vertical centre of the
    // glyph cell is at baseline_y - baseline + height/2.
    auto baseline_for_centre = [&](const Font &f, int centre_y) {
        return centre_y + f.baseline() - f.height() / 2;
    };
    auto draw_rect = [&](int x, int y, int w, int h, const Color &col) {
        for (int dx = 0; dx < w; ++dx) {
            grid.SetPixel(x + dx, y,             col.r, col.g, col.b);
            grid.SetPixel(x + dx, y + h - 1,     col.r, col.g, col.b);
        }
        for (int dy = 0; dy < h; ++dy) {
            grid.SetPixel(x,         y + dy,     col.r, col.g, col.b);
            grid.SetPixel(x + w - 1, y + dy,     col.r, col.g, col.b);
        }
    };

    // Blit an RGBA pixel buffer onto the canvas with nearest-neighbour scaling.
    // Pixels with alpha < 128 are skipped (transparent). Sharp pixel edges are
    // preferable to interpolation when the destination is an LED grid.
    // The image is fit (preserving aspect ratio) inside the dst_w × dst_h box
    // and centred — so a non-square source isn't squashed when the box is square.
    auto draw_rgba_image = [&](const unsigned char *data, int src_w, int src_h,
                               int dst_x, int dst_y, int dst_w, int dst_h) {
        if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) return;
        int fit_w = dst_w, fit_h = dst_h;
        if (src_w * dst_h > src_h * dst_w) {
            fit_h = (dst_w * src_h) / src_w;
        } else {
            fit_w = (dst_h * src_w) / src_h;
        }
        const int ox = dst_x + (dst_w - fit_w) / 2;
        const int oy = dst_y + (dst_h - fit_h) / 2;
        for (int py = 0; py < fit_h; ++py) {
            int sy = py * src_h / fit_h;
            const unsigned char *row = data + 4 * sy * src_w;
            for (int px = 0; px < fit_w; ++px) {
                int sx = px * src_w / fit_w;
                const unsigned char *p = row + 4 * sx;
                if (p[3] < 128) continue;
                grid.SetPixel(ox + px, oy + py, p[0], p[1], p[2]);
            }
        }
    };

    // Load the club crest (RGBA). Path is relative to the binary's CWD on the Pi.
    int logo_w = 0, logo_h = 0, logo_channels = 0;
    unsigned char *logo_data = stbi_load("assets/resized_logo.bmp",
                                         &logo_w, &logo_h, &logo_channels, 4);
    if (!logo_data) {
        fprintf(stderr, "Warning: failed to load logo 'assets/resized_logo.bmp': %s\n",
                stbi_failure_reason());
    }

    // ---------- Phase drawing routines ----------
    //
    // SwapOnVSync is always a full-frame swap — there is no partial-swap API.
    // To avoid the timer-driven flicker we hit on 2026-05-15, swaps happen
    // ONLY when the published MatchState generation changes. Within a single
    // change event, we draw the new frame on the back buffer, swap, then
    // mirror the same drawing into the new back buffer so both stay aligned.
    char buf[64];

    auto draw_scoreboard = [&](const MatchState &s) {
        grid.Fill(0, 0, 0);

        // ===== Row A LEFT : club crest =====
        // 96 × 112 slot, top-left at (2, 2). With the resized_logo.bmp
        // source being exactly 96×112, draw_rgba_image renders it 1:1 (no
        // scaling). Slot extends to (98, 114) — into Row B's territory, so
        // the RUNS row + everything below it shifts down 6 px to give the
        // logo's lower edge clear air above the RUNS text.
        constexpr int kLogoX = 2, kLogoY = 2;
        constexpr int kLogoW = 96, kLogoH = 112;
        if (logo_data && logo_w > 0 && logo_h > 0) {
            draw_rgba_image(logo_data, logo_w, logo_h,
                            kLogoX, kLogoY, kLogoW, kLogoH);
        } else {
            draw_rect(kLogoX, kLogoY, kLogoW, kLogoH, c_grey);
            draw_centered(font_label, kLogoX + kLogoW / 2,
                          kLogoY + kLogoH / 2 + 4, c_white, "LOGO");
        }

        // ===== Row A MID : match title (home / vs / opponent, 3 stacked lines) =====
        // 3 lines of 20px fit in 64px row A with ~2px padding top/bottom.
        draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 12),
                      c_cyan,  s.home_team.c_str());
        draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 32),
                      c_white, "vs");
        draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 52),
                      c_green, s.opponent.c_str());

        // ===== Row A RIGHT : TO WIN <target>  (only when chasing) =====
        if (s.chasing) {
            // TO / WIN stacked in the col-5 (A5) half of the right band.
            draw_centered(font_label, kRightCx - 32,
                          baseline_for_centre(font_label, 22), c_white, "TO");
            draw_centered(font_label, kRightCx - 32,
                          baseline_for_centre(font_label, 42), c_white, "WIN");
            snprintf(buf, sizeof(buf), "%d", s.target);
            // Number 1: panel A6 centreline (352, 32).
            draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 32),
                          c_amber, buf);
        }

        // Row B / Row C / Row D-batters shift +6 px down from the original
        // spec to clear the taller 96×112 logo. LAST INNS (Row D RIGHT) stays
        // at its original y so it doesn't run off the bottom of the canvas.

        // ===== Row B LEFT : "RUNS" label =====
        // Left-justified at x = kLeftCx - 50 = 14, same x as BAT 1 / BAT 2.
        draw_left(font_label_big, kLeftCx - 50,
                  baseline_for_centre(font_label_big, 127), c_white, "RUNS");

        // ===== Row B MID : runs total (large; the main score) =====
        snprintf(buf, sizeof(buf), "%d", s.runs);
        draw_centered(font_score, kMidCx - 12, baseline_for_centre(font_score, 114),
                      c_amber, buf);

        // ===== Row B RIGHT : WKTS <count> =====
        draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 96),
                      c_white, "WKTS");
        snprintf(buf, sizeof(buf), "%d", s.wkts);
        draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 96),
                      c_red, buf);

        // ===== Row C LEFT : BAT 1 + name (* on strike) =====
        draw_left(font_label_big, kLeftCx - 50,
                  baseline_for_centre(font_label_big, 163), c_white, "BAT 1");
        snprintf(buf, sizeof(buf), "%s%s",
                 s.bat1_name.c_str(), s.on_strike == 1 ? " *" : "");
        draw_left(font_label, kLeftCx - 50, baseline_for_centre(font_label, 187),
                  c_cyan, buf);

        // ===== Row C MID : bat 1 score =====
        snprintf(buf, sizeof(buf), "%d", s.bat1_score);
        draw_centered(font_small_num, kMidCx - 12, baseline_for_centre(font_small_num, 179),
                      c_white, buf);

        // ===== Row C RIGHT : OVERS <count> =====
        draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 160),
                      c_white, "OVERS");
        const char *overs_str = s.overs.empty() ? "-" : s.overs.c_str();
        draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 160),
                      c_green, overs_str);

        // ===== Row D LEFT : BAT 2 + name (* on strike) =====
        draw_left(font_label_big, kLeftCx - 50,
                  baseline_for_centre(font_label_big, 222), c_white, "BAT 2");
        snprintf(buf, sizeof(buf), "%s%s",
                 s.bat2_name.c_str(), s.on_strike == 2 ? " *" : "");
        draw_left(font_label, kLeftCx - 50, baseline_for_centre(font_label, 246),
                  c_cyan, buf);

        // ===== Row D MID : bat 2 score =====
        snprintf(buf, sizeof(buf), "%d", s.bat2_score);
        draw_centered(font_small_num, kMidCx - 12, baseline_for_centre(font_small_num, 236),
                      c_white, buf);

        // ===== Row D RIGHT : LAST INNS <runs> <wkts> =====
        // "INNINGS" was renamed to "INNS" so it fits at the larger label font.
        // Only drawn when chasing (the field is blank when batting first per plan).
        if (s.chasing) {
            draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 208),
                          c_white, "LAST");
            draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 240),
                          c_white, "INNS");
            snprintf(buf, sizeof(buf), "%d", s.last_inn_runs);
            // Number 7: row D's 1/4 line (352, 208).
            draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 208),
                          c_amber, buf);
            snprintf(buf, sizeof(buf), "%d", s.last_inn_wkts);
            // Number 8: row D's 3/4 line (352, 240).
            draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 240),
                          c_amber, buf);
        }
    };

    // Pre-match splash A. Per plan (2026-05-17):
    //   Home block: vertical-centred on the A/B boundary (y=64)
    //   VS:         pure canvas centre (192, 128), 60pt
    //   Away block: vertical-centred on the C/D boundary (y=192)
    // A "block" is a single 30pt line when team_name == club_name, or a
    // two-line club-over-team stack (30pt + 10x20, 4 px gap) otherwise.
    auto draw_side_block = [&](int anchor_y,
                               const std::string &club_name,
                               const std::string &team_name,
                               const Color &col) {
        const bool one_line = team_name.empty() || team_name == club_name;
        if (one_line) {
            draw_centered(font_label_big, kMidCx,
                          baseline_for_centre(font_label_big, anchor_y),
                          col, club_name.c_str());
            return;
        }
        const int club_h    = font_label_big.height();
        const int team_h    = font_label.height();
        constexpr int gap   = 4;
        const int combined  = club_h + gap + team_h;
        const int block_top = anchor_y - combined / 2;
        const int club_cy   = block_top + club_h / 2;
        const int team_cy   = block_top + club_h + gap + team_h / 2;
        draw_centered(font_label_big, kMidCx,
                      baseline_for_centre(font_label_big, club_cy),
                      col, club_name.c_str());
        draw_centered(font_label, kMidCx,
                      baseline_for_centre(font_label, team_cy),
                      col, team_name.c_str());
    };

    auto draw_pre_match = [&](const MatchState &s) {
        grid.Fill(0, 0, 0);
        draw_side_block(64,  s.home_club_name, s.home_team_name, c_cyan);
        draw_centered(font_score, kMidCx,
                      baseline_for_centre(font_score, 128),
                      c_white, "VS");
        draw_side_block(192, s.away_club_name, s.away_team_name, c_green);
    };

    // Post-match splash B. Per plan (2026-05-17):
    //   Row A centre (y=32):  result_description, 30pt amber, falls back to
    //                         10x20 if width > 380 px (canvas is 384 px wide).
    //   Pure centre  (y=128): inn1 summary in 10x20 white.
    //   Row D centre (y=224): inn2 summary in 10x20 white.
    // Symmetric 96 px between anchors.
    // Text-only portion of the POST_MATCH splash. Does NOT clear -- callers
    // either fill black first (normal path) or render fireworks behind first
    // (PostMatchFireworks interlude).
    auto draw_post_match_text = [&](const MatchState &s) {
        if (!s.result_description.empty()) {
            constexpr int kMaxHeadlineWidth = 380;
            const char *result_text = s.result_description.c_str();
            const Font &result_font =
                text_width(font_label_big, result_text) > kMaxHeadlineWidth
                    ? font_label : font_label_big;
            draw_centered(result_font, kMidCx,
                          baseline_for_centre(result_font, 32),
                          c_amber, result_text);
        }

        auto draw_innings = [&](int centre_y, const cricketboard::InningsSummary &inn) {
            if (!inn.valid) return;
            char line[160];
            snprintf(line, sizeof(line), "%s  %d/%d  (%s)",
                     inn.team_name.c_str(), inn.runs, inn.wkts, inn.overs.c_str());
            draw_centered(font_label, kMidCx,
                          baseline_for_centre(font_label, centre_y),
                          c_white, line);
        };
        draw_innings(128, s.inn1);
        draw_innings(224, s.inn2);
    };

    auto draw_post_match = [&](const MatchState &s) {
        grid.Fill(0, 0, 0);
        draw_post_match_text(s);
    };

    // Idle screen for NO_MATCH. Keeps the wall visibly alive — logo centred,
    // no text. Full layout will be a follow-up.
    auto draw_idle = [&]() {
        grid.Fill(0, 0, 0);
        if (logo_data && logo_w > 0 && logo_h > 0) {
            const int size = 160;
            const int x = (grid.width()  - size) / 2;
            const int y = (grid.height() - size) / 2;
            draw_rgba_image(logo_data, logo_w, logo_h, x, y, size, size);
        }
    };

    auto draw_phase = [&](const MatchState &s) {
        switch (s.phase) {
            case MatchPhase::PRE_MATCH:  draw_pre_match(s);  break;
            case MatchPhase::IN_MATCH:   draw_scoreboard(s); break;
            case MatchPhase::POST_MATCH: draw_post_match(s); break;
            case MatchPhase::NO_MATCH:   draw_idle();        break;
        }
    };

    Fireworks fireworks;

    // Render one frame for the currently-active interlude (or fall back to
    // the static phase view if none).
    auto draw_frame = [&](const MatchState &s, Interlude active, float dt) {
        switch (active) {
            case Interlude::Wicket:
            case Interlude::Four:
            case Interlude::Six:
                grid.Fill(0, 0, 0);
                DrawEventSplash(grid, font_impact, active);
                return;
            case Interlude::PostMatchFireworks:
                grid.Fill(0, 0, 0);
                fireworks.StepAndDraw(grid, dt);
                draw_post_match_text(s);
                return;
            case Interlude::None:
            default:
                draw_phase(s);
                return;
        }
    };

    // ---------- Demo-splash short-circuit ----------
    if (demo_mode) {
        printf("Demo mode: rendering %s for %s seconds. Ctrl+C to exit.\n",
               demo_splash == Interlude::Wicket             ? "Wicket!"   :
               demo_splash == Interlude::Four               ? "Four!"     :
               demo_splash == Interlude::Six                ? "Six!"      :
               demo_splash == Interlude::PostMatchFireworks ? "fireworks" : "?",
               demo_splash == Interlude::PostMatchFireworks ? "30" : "12");
        MatchState fake;
        fake.phase = (demo_splash == Interlude::PostMatchFireworks)
                       ? MatchPhase::POST_MATCH : MatchPhase::NO_MATCH;
        fake.result_description = "DEMO -- result_description";
        fake.inn1.valid = false;
        fake.inn2.valid = false;

        const auto start = std::chrono::steady_clock::now();
        auto last_anim   = start;
        const float budget = (demo_splash == Interlude::PostMatchFireworks) ? 30.f : 12.f;
        while (!interrupt_received) {
            const auto now = std::chrono::steady_clock::now();
            const float dt = std::chrono::duration<float>(now - last_anim).count();
            last_anim = now;

            draw_frame(fake, demo_splash, dt);
            display->swap_on_vsync();
            grid.set_backing(display->current_back_buffer());

            const float elapsed = std::chrono::duration<float>(now - start).count();
            if (elapsed > budget) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        display->clear();
        if (logo_data) stbi_image_free(logo_data);
        printf("\nDemo done.\n");
        return 0;
    }

    // ---------- Live match plumbing ----------
    SharedMatchState shared_state;
    PollLoop poller(cfg, &shared_state, &interrupt_received);
    poller.start();

    // ---------- Phone-accessible debug server (fail-closed on empty password) ----------
    std::unique_ptr<DebugServer> debug_server;
    if (cfg.debug_server_enabled) {
        if (cfg.debug_server_password.empty()) {
            fprintf(stderr,
                    "Debug server NOT started: debug_server_password is empty in config.json.\n");
        } else {
            debug_server = std::make_unique<DebugServer>(
                &shared_state, cfg.debug_server_password, cfg.debug_server_port,
                cfg.repo_dir, cfg.scripts_dir, cfg.api_base_url);
            debug_server->start();
        }
    }

    // Render loop. Two pacing modes:
    //   Idle (no interlude active): block on the state-change condvar with a
    //     500 ms wakeup, redraw only on generation change. Same idle-CPU
    //     behaviour as before.
    //   Animating: short 20 ms timeout so fireworks/splashes advance at ~50 fps
    //     even while state is static.
    uint64_t   last_gen = static_cast<uint64_t>(-1);
    MatchState prev;                                   // for DetectEvent
    Interlude  active = Interlude::None;
    auto       active_start = std::chrono::steady_clock::now();
    auto       last_anim    = active_start;

    while (!interrupt_received) {
        const auto timeout = (active != Interlude::None)
                               ? std::chrono::milliseconds(20)
                               : std::chrono::milliseconds(500);
        MatchState s = shared_state.wait_for_update(last_gen, timeout, interrupt_received);
        if (interrupt_received) break;

        const bool state_changed = (s.generation != last_gen);
        if (state_changed) {
            const Interlude triggered = DetectEvent(prev, s);
            if (triggered != Interlude::None) {
                // Cancel-and-replace: newer event wins, timer resets.
                active = triggered;
                active_start = std::chrono::steady_clock::now();
            }
            prev = s;
        }

        // Auto-expire short splashes after 10 s. PostMatchFireworks runs as
        // long as we're in POST_MATCH; it clears when phase changes back.
        if (active == Interlude::Wicket || active == Interlude::Four || active == Interlude::Six) {
            const auto elapsed = std::chrono::steady_clock::now() - active_start;
            if (elapsed >= std::chrono::seconds(10)) {
                active = Interlude::None;
            }
        } else if (active == Interlude::PostMatchFireworks && s.phase != MatchPhase::POST_MATCH) {
            active = Interlude::None;
        }

        const bool animating = (active != Interlude::None);
        if (!state_changed && !animating) continue;    // preserve idle-cheap path

        const auto now = std::chrono::steady_clock::now();
        const float dt = std::chrono::duration<float>(now - last_anim).count();
        last_anim = now;

        draw_frame(s, active, dt);
        display->swap_on_vsync();
        grid.set_backing(display->current_back_buffer());
        draw_frame(s, active, dt);                     // mirror into new back buffer
        last_gen = s.generation;
    }

    if (debug_server) debug_server->stop();
    poller.join();
    if (logo_data) stbi_image_free(logo_data);
    display->clear();
    printf("\nDone.\n");
    return 0;
}
