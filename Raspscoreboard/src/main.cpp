#include "led-matrix.h"
#include "graphics.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

using namespace rgb_matrix;

// Global flag for clean shutdown on Ctrl+C
volatile bool interrupt_received = false;
static void InterruptHandler(int signo) {
    interrupt_received = true;
}

int main(int argc, char *argv[]) {
    // -------------------------------------------------------------------------
    // Matrix configuration — adjust these to match your hardware setup
    // -------------------------------------------------------------------------
    RGBMatrix::Options matrix_options;
    matrix_options.hardware_mapping = "regular";  // Electrodragon board = "regular"
    matrix_options.rows = 64;           // Panel height in pixels
    matrix_options.cols = 64;           // Panel width in pixels
    matrix_options.chain_length = 3;    // Three panels daisy-chained
    matrix_options.parallel = 1;        // Single chain for initial test
    matrix_options.brightness = 50;     // 1-100 percent
    matrix_options.pwm_bits = 7;        // Reduced from 11 for less flicker

    rgb_matrix::RuntimeOptions runtime_options;
    runtime_options.gpio_slowdown = 4;  // Tuned for Pi 3B with 64x64 panel

    // Parse flags from command line (overrides defaults above)
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

    // Use an off-screen canvas for flicker-free rendering
    FrameCanvas *canvas = matrix->CreateFrameCanvas();

    // Load fonts for text rendering
    const char *base = "lib/rpi-rgb-led-matrix/fonts/";
    char path[256];

    rgb_matrix::Font font_label;      // OVERS, WKTS labels
    snprintf(path, sizeof(path), "%s7x13B.bdf", base);
    if (!font_label.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    rgb_matrix::Font font_runs_label; // RUNS label (bigger)
    snprintf(path, sizeof(path), "%s10x20.bdf", base);
    if (!font_runs_label.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    rgb_matrix::Font font_number;     // Score numbers
    snprintf(path, sizeof(path), "%stexgyre-27.bdf", base);
    if (!font_number.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    int canvas_w = matrix->width();
    int canvas_h = matrix->height();
    printf("Scoreboard row 2 test on %dx%d canvas. Press Ctrl+C to exit.\n",
           canvas_w, canvas_h);

    Color white(255, 255, 255);
    Color green(0, 200, 0);
    Color yellow(255, 255, 0);
    Color orange(255, 165, 0);

    // Example score values
    const char *overs_val = "24";
    const char *runs_val = "187";
    const char *wkts_val = "04";

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);

        // --- Labels at top ---

        // OVERS label: 1/3 into left panel = x ~21, centred
        // 7x13B: "OVERS" = 5*7 = 35px, start at 21 - 17 = 4
        DrawText(canvas, font_label, 4, 13, white, nullptr, "OVERS", 0);

        // RUNS label: centred on middle panel
        // 10x20: "RUNS" = 4*10 = 40px, centre at x=96, start at 76
        DrawText(canvas, font_runs_label, 76, 20, white, nullptr, "RUNS", 0);

        // WKTS label: 2/3 into right panel = x ~171, centred
        // 7x13B: "WKTS" = 4*7 = 28px, start at 171 - 14 = 157
        DrawText(canvas, font_label, 157, 13, white, nullptr, "WKTS", 0);

        // --- Numbers below labels ---

        // Overs (2-digit, green): centred under OVERS at x~21
        // texgyre-27: ~15px per digit, 2 digits = 30px, start at 21 - 15 = 6
        DrawText(canvas, font_number, 6, 60, green, nullptr, overs_val, 0);

        // Runs (3-digit, yellow): centred on middle panel, bottom of panel
        // texgyre-27: ~15px per digit, 3 digits = 45px, centre at 96, start at 74
        DrawText(canvas, font_number, 74, 62, yellow, nullptr, runs_val, 0);

        // Wkts (2-digit, orange): centred under WKTS at x~171
        // texgyre-27: ~15px per digit, 2 digits = 30px, start at 171 - 15 = 156
        DrawText(canvas, font_number, 156, 60, orange, nullptr, wkts_val, 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
