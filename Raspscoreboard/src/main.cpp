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

    rgb_matrix::Font font_number;     // OVERS/WKTS numbers
    if (!font_number.LoadFont("fonts/dejavu-mono-bold-42.bdf"))
        fprintf(stderr, "Warning: could not load number font\n");

    rgb_matrix::Font font_runs_num;   // RUNS number (large bold)
    if (!font_runs_num.LoadFont("fonts/dejavu-mono-bold-46.bdf"))
        fprintf(stderr, "Warning: could not load runs number font\n");

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
    const char *wkts_val = "4";

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);

        // --- Labels at top (aligned tops) ---
        // 7x13B ascent ~11, so top = y - 11. For top=1: y=12
        // 10x20 ascent ~16, so top = y - 16. For top=1: y=17

        // OVERS label: 1/3 into left panel
        DrawText(canvas, font_label, 4, 12, white, nullptr, "OVERS", 0);

        // RUNS label: centred on middle panel
        DrawText(canvas, font_runs_label, 76, 17, white, nullptr, "RUNS", 0);

        // WKTS label: 2/3 into right panel
        DrawText(canvas, font_label, 157, 12, white, nullptr, "WKTS", 0);

        // --- Numbers (tops aligned) ---
        // dejavu-bold-42 ascent ~31, for top=26: y=57
        // dejavu-bold-46 ascent ~34, for top=26: y=60

        // Overs (2-digit, green): centred under OVERS at x~21
        // dejavu-bold-42: 25px per digit, 2 digits = 50px, start at 21 - 25 = -4
        DrawText(canvas, font_number, -4, 57, green, nullptr, overs_val, 0);

        // Runs (3-digit, yellow): centred on middle panel
        // dejavu-bold-46: 28px per digit, 3 digits = 84px, centre at 96, start at 54
        DrawText(canvas, font_runs_num, 54, 60, yellow, nullptr, runs_val, 0);

        // Wkts (orange): centred under WKTS at x~171
        // dejavu-bold-42: 25px per digit, centre based on digit count
        int wkts_width = strlen(wkts_val) * 25;
        DrawText(canvas, font_number, 171 - wkts_width / 2, 57, orange, nullptr, wkts_val, 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
