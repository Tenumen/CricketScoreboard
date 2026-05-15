#include "led-matrix.h"
#include "graphics.h"

#include "calibration.h"
#include "grid_canvas.h"
#include "panel_layout.h"

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#include "stb_image.h"

#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

using namespace rgb_matrix;
using cricketboard::GridCanvas;
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

int main(int argc, char *argv[]) {
    cricketboard::CalibrationMode cal_mode = cricketboard::CalibrationMode::Sequential;
    const bool calibrate = ExtractCalibrateFlag(&argc, argv, &cal_mode);

    RGBMatrix::Options matrix_options;
    matrix_options.hardware_mapping = "regular";   // Electrodragon HAT
    matrix_options.rows         = 64;
    matrix_options.cols         = 64;
    matrix_options.chain_length = cricketboard::kChainLength;     // 8 per HAT output
    matrix_options.parallel     = cricketboard::kParallelChains;  // 3 HAT outputs
    matrix_options.brightness   = 50;
    matrix_options.pwm_bits     = 6;              // 64 brightness levels — enough for text; ~4x more refresh headroom than 8
    matrix_options.multiplexing = 1;              // ICN2037DP @ 1/16 scan needs "Stripe" mapping
    matrix_options.show_refresh_rate = true;      // print achieved Hz to stderr while running
    matrix_options.limit_refresh_rate_hz = 120;   // cap refresh so timing is stable, not racing
    // matrix_options.led_rgb_sequence = "RGB";   // try permutations if colours are wrong
    // matrix_options.panel_type   = "FM6126A";   // uncomment if ICN2037 needs the FM init sequence

    RuntimeOptions runtime_options;
    runtime_options.gpio_slowdown = 3;            // 3 suits 8-panel chains on Pi 3B; try 4 if still flickery
    runtime_options.drop_privileges = -1;         // stay root after init so refresh thread can hold realtime priority

    if (!ParseOptionsFromFlags(&argc, &argv, &matrix_options, &runtime_options)) {
        PrintMatrixFlags(stderr, matrix_options, runtime_options);
        return 1;
    }

    RGBMatrix *matrix = RGBMatrix::CreateFromOptions(matrix_options, runtime_options);
    if (matrix == nullptr) {
        fprintf(stderr, "Could not create matrix. Are you running as root?\n");
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
        cricketboard::RunCalibration(matrix, font_label, cal_mode, &interrupt_received);
        matrix->Clear();
        delete matrix;
        printf("\nCalibration ended.\n");
        return 0;
    }

    Font font_score;  // large — main runs total only
    if (!font_score.LoadFont("fonts/liberation-mono-bold-60.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-60.bdf'\n");

    Font font_small_num;  // small — every other number on the board
    if (!font_small_num.LoadFont("fonts/liberation-mono-bold-35.bdf"))
        fprintf(stderr, "Warning: could not load font 'fonts/liberation-mono-bold-35.bdf'\n");

    FrameCanvas *frame = matrix->CreateFrameCanvas();
    GridCanvas grid(frame);

    printf("Scoreboard24 running on %dx%d logical canvas (HW %dx%d). Ctrl+C to exit.\n",
           grid.width(), grid.height(),
           matrix->width(), matrix->height());

    // ---------- Colour palette (DISPLAY_NOTES_24.md spec) ----------
    Color c_white(255, 255, 255);
    Color c_cyan (100, 200, 255);
    Color c_green(  0, 220,   0);
    Color c_amber(255, 165,   0);
    Color c_red  (255, 110, 110);  // lighter — more luminance for distance readability
    Color c_grey ( 80,  80,  80);

    // ---------- Sample state (will be replaced by live data later) ----------
    const char *home_team    = "ASTON ON TRENT";
    const char *opponent     = "MELBOURNE";
    bool        chasing      = true;
    int         target       = 287;
    int         runs         = 245;
    int         wkts         = 6;
    int         overs        = 38;
    const char *bat1_name    = "ARUN";
    int         bat1_score   = 67;
    const char *bat2_name    = "JAKE";
    int         bat2_score   = 34;
    int         on_strike    = 1;          // 1 = bat1, 2 = bat2
    int         last_inn_runs = 287;
    int         last_inn_wkts = 11;

    // ---------- Layout anchors (3 cols × 4 rows of 128×64 cells) ----------
    // Naming is from the AUDIENCE viewpoint. After grid_canvas.cpp was corrected
    // (col 1 = audience-left, not audience-right), low x = audience-left.
    constexpr int kColLeft  = 0,   kColMid   = 128, kColRight = 256, kColW = 128;
    constexpr int kRowA     = 0,   kRowB     = 64,  kRowC     = 128, kRowD = 192;
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
    auto draw_rgba_image = [&](const unsigned char *data, int src_w, int src_h,
                               int dst_x, int dst_y, int dst_w, int dst_h) {
        for (int py = 0; py < dst_h; ++py) {
            int sy = py * src_h / dst_h;
            const unsigned char *row = data + 4 * sy * src_w;
            for (int px = 0; px < dst_w; ++px) {
                int sx = px * src_w / dst_w;
                const unsigned char *p = row + 4 * sx;
                if (p[3] < 128) continue;
                grid.SetPixel(dst_x + px, dst_y + py, p[0], p[1], p[2]);
            }
        }
    };

    // Load the club crest (RGBA). Path is relative to the binary's CWD on the Pi.
    int logo_w = 0, logo_h = 0, logo_channels = 0;
    unsigned char *logo_data = stbi_load("assets/logo_64.png",
                                         &logo_w, &logo_h, &logo_channels, 4);
    if (!logo_data) {
        fprintf(stderr, "Warning: failed to load logo 'assets/logo_64.png': %s\n",
                stbi_failure_reason());
    }

    // Draw once. The library's refresh daemon keeps the display live, so we only
    // call SwapOnVSync again when the content actually changes.
    //
    // Partial-update pattern (for when live score data is wired up):
    //   SwapOnVSync is always a full-frame swap — there is no partial-swap API.
    //   But visually, only changed pixels appear to change. To update one value
    //   (e.g. wickets) without disturbing the rest:
    //     1. Clear only the rectangle holding that value in the back buffer.
    //     2. Redraw the new value into that rectangle.
    //     3. matrix->SwapOnVSync(frame)  — front now shows the update.
    //     4. Mirror the same single-region update into the NEW back buffer
    //        (which still holds the OLD value) so both buffers stay in sync.
    //   Never redraw the full frame on a timer — that reintroduces the swap
    //   glitch fixed on 2026-05-15.
    grid.Fill(0, 0, 0);

    char buf[32];

    // ===== Row A LEFT : club crest =====
    // Bounding box (margin 2 px from extremity inside):
    //   left  =  2 (2 px from display left edge)
    //   top   =  2 (2 px from display top edge)
    //   right = 98 (12 px to the left of the "A" of ASTON ON TRENT at x=110)
    //   bot   = 88 (6 px above the top of the RUNS text)
    // Box is 96 wide × 86 tall. With 1:1 aspect the height is the tighter
    // constraint: 82×82 logo gives the requested 2 px top/bottom margins and
    // 7 px each side. Top-left lands at (9, 4).
    constexpr int kLogoX = 9, kLogoY = 4;
    constexpr int kLogoSize = 82;
    if (logo_data && logo_w > 0 && logo_h > 0) {
        draw_rgba_image(logo_data, logo_w, logo_h,
                        kLogoX, kLogoY, kLogoSize, kLogoSize);
    } else {
        draw_rect(kLogoX, kLogoY, kLogoSize, kLogoSize, c_grey);
        draw_centered(font_label, kLogoX + kLogoSize / 2,
                      kLogoY + kLogoSize / 2 + 4, c_white, "LOGO");
    }

    // ===== Row A MID : match title (home / vs / opponent, 3 stacked lines) =====
    // 3 lines of 20px fit in 64px row A with ~2px padding top/bottom.
    draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 12),
                  c_cyan,  home_team);
    draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 32),
                  c_white, "vs");
    draw_centered(font_label, kMidCx - 12, baseline_for_centre(font_label, 52),
                  c_green, opponent);

    // ===== Row A RIGHT : TO WIN <target>  (only when chasing) =====
    if (chasing) {
        // TO / WIN stacked in the col-5 (A5) half of the right band.
        draw_centered(font_label, kRightCx - 32,
                      baseline_for_centre(font_label, 22), c_white, "TO");
        draw_centered(font_label, kRightCx - 32,
                      baseline_for_centre(font_label, 42), c_white, "WIN");
        snprintf(buf, sizeof(buf), "%d", target);
        // Number 1: panel A6 centreline (352, 32).
        draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 32),
                      c_amber, buf);
    }

    // ===== Row B LEFT : "RUNS" label =====
    // Left-justified at x = kLeftCx - 50 = 14, same x as BAT 1 / BAT 2.
    draw_left(font_label_big, kLeftCx - 50,
              baseline_for_centre(font_label_big, 109), c_white, "RUNS");

    // ===== Row B MID : runs total (large; the main score) =====
    snprintf(buf, sizeof(buf), "%d", runs);
    // Number 2: centred between B3 and B4 at (192, 112) (16 px lower than centreline).
    draw_centered(font_score, kMidCx - 12, baseline_for_centre(font_score, 112),
                  c_amber, buf);

    // ===== Row B RIGHT : WKTS <count> =====
    draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 96),
                  c_white, "WKTS");
    snprintf(buf, sizeof(buf), "%d", wkts);
    // Number 3: panel B6 centreline (352, 96).
    draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 96),
                  c_red, buf);

    // ===== Row C LEFT : BAT 1 + name (* on strike) =====
    // Left-justified at x = kLeftCx - 50 = 14. BAT 1 label uses font_label_big
    // (~50% larger than the name font). Label centred on row C panel 1/4 line
    // (y=144); name on 3/4 line (y=176) at standard font_label.
    draw_left(font_label_big, kLeftCx - 50,
              baseline_for_centre(font_label_big, 157), c_white, "BAT 1");
    snprintf(buf, sizeof(buf), "%s%s", bat1_name, on_strike == 1 ? " *" : "");
    draw_left(font_label, kLeftCx - 50, baseline_for_centre(font_label, 189),
              c_cyan, buf);

    // ===== Row C MID : bat 1 score =====
    snprintf(buf, sizeof(buf), "%d", bat1_score);
    // Number 4: centred between C3 and C4 at (192, 176) (16 px lower than centreline).
    draw_centered(font_small_num, kMidCx - 12, baseline_for_centre(font_small_num, 176),
                  c_white, buf);

    // ===== Row C RIGHT : OVERS <count> =====
    draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 160),
                  c_white, "OVERS");
    snprintf(buf, sizeof(buf), "%d", overs);
    // Number 5: panel C6 centreline (352, 160).
    draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 160),
                  c_green, buf);

    // ===== Row D LEFT : BAT 2 + name (* on strike) =====
    // Left-justified at x = kLeftCx - 50 = 14. BAT 2 label uses font_label_big;
    // name uses standard font_label. Label on row D panel 1/4 line (y=208);
    // name on 3/4 line (y=240).
    draw_left(font_label_big, kLeftCx - 50,
              baseline_for_centre(font_label_big, 221), c_white, "BAT 2");
    snprintf(buf, sizeof(buf), "%s%s", bat2_name, on_strike == 2 ? " *" : "");
    draw_left(font_label, kLeftCx - 50, baseline_for_centre(font_label, 245),
              c_cyan, buf);

    // ===== Row D MID : bat 2 score =====
    snprintf(buf, sizeof(buf), "%d", bat2_score);
    // Number 6: centred between D3 and D4 at (192, 240) (16 px lower than centreline).
    draw_centered(font_small_num, kMidCx - 12, baseline_for_centre(font_small_num, 240),
                  c_white, buf);

    // ===== Row D RIGHT : LAST INNS <runs> <wkts> =====
    // "INNINGS" was renamed to "INNS" so it fits at the larger label font.
    draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 208),
                  c_white, "LAST");
    draw_centered(font_label, kRightCx - 32, baseline_for_centre(font_label, 240),
                  c_white, "INNS");
    snprintf(buf, sizeof(buf), "%d", last_inn_runs);
    // Number 7: row D's 1/4 line (352, 208).
    draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 208),
                  c_amber, buf);
    snprintf(buf, sizeof(buf), "%d", last_inn_wkts);
    // Number 8: row D's 3/4 line (352, 240).
    draw_centered(font_small_num, 350, baseline_for_centre(font_small_num, 240),
                  c_amber, buf);

    matrix->SwapOnVSync(frame);

    while (!interrupt_received) {
        usleep(100 * 1000);
    }

    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
