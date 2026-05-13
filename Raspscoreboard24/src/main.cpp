#include "led-matrix.h"
#include "graphics.h"

#include "calibration.h"
#include "grid_canvas.h"
#include "panel_layout.h"

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
    matrix_options.pwm_bits     = 11;             // P3 outdoor + 1920Hz refresh
    matrix_options.multiplexing = 1;              // ICN2037DP @ 1/16 scan needs "Stripe" mapping
    // matrix_options.led_rgb_sequence = "RGB";   // try permutations if colours are wrong
    // matrix_options.panel_type   = "FM6126A";   // uncomment if ICN2037 needs the FM init sequence

    RuntimeOptions runtime_options;
    runtime_options.gpio_slowdown = 2;            // bump to 3 or 4 if there's flicker/ghosting

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
    snprintf(path, sizeof(path), "%s7x13B.bdf", base);
    if (!font_label.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    if (calibrate) {
        cricketboard::RunCalibration(matrix, font_label, cal_mode, &interrupt_received);
        matrix->Clear();
        delete matrix;
        printf("\nCalibration ended.\n");
        return 0;
    }

    Font font_number;
    if (!font_number.LoadFont("fonts/dejavu-mono-bold-42.bdf"))
        fprintf(stderr, "Warning: could not load number font 'fonts/dejavu-mono-bold-42.bdf'\n");

    FrameCanvas *frame = matrix->CreateFrameCanvas();
    GridCanvas grid(frame);

    printf("Scoreboard24 running on %dx%d logical canvas (HW %dx%d). Ctrl+C to exit.\n",
           grid.width(), grid.height(),
           matrix->width(), matrix->height());

    Color white(255, 255, 255);
    Color yellow(255, 255, 0);

    const char *last_inn_runs = "137";
    const char *last_inn_wkts = "11";

    // LAST INNINGS placed in panel row D (y = 192..255), centred horizontally on
    // the 384-wide logical canvas. Coordinates ported from the legacy 192-wide
    // layout: legacy x + 96 -> new x; legacy y + 192 -> new y.
    constexpr int kRowDTop = 3 * kPanelPx;  // 192

    while (!interrupt_received) {
        grid.Fill(0, 0, 0);

        DrawText(&grid, font_label, 150, kRowDTop + 12, white,  nullptr, "LAST INNINGS", 0);
        DrawText(&grid, font_number, 109, kRowDTop + 60, yellow, nullptr, last_inn_runs, 0);
        DrawText(&grid, font_label,  192, kRowDTop + 48, yellow, nullptr, "/",           0);
        DrawText(&grid, font_number, 206, kRowDTop + 60, yellow, nullptr, last_inn_wkts, 0);

        frame = matrix->SwapOnVSync(frame);
        grid.set_backing(frame);
        usleep(500 * 1000);
    }

    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
