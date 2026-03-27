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

    rgb_matrix::Font font_label;      // Labels (7x13B)
    snprintf(path, sizeof(path), "%s7x13B.bdf", base);
    if (!font_label.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    rgb_matrix::Font font_number;     // Score numbers (dejavu-bold-42)
    if (!font_number.LoadFont("fonts/dejavu-mono-bold-42.bdf"))
        fprintf(stderr, "Warning: could not load number font\n");

    int canvas_w = matrix->width();
    int canvas_h = matrix->height();
    printf("Scoreboard row 3 test on %dx%d canvas. Press Ctrl+C to exit.\n",
           canvas_w, canvas_h);

    Color white(255, 255, 255);
    Color blue(0, 100, 255);

    // Each half is 96px wide (1.5 panels)
    // BAT 1 centre: 1/3 of left half = 96/3 = 32
    // BAT 2 centre: right half start (96) + 2/3 of 96 = 96 + 64 = 160

    // Example values
    const char *bat1_label = "BAT 1";
    const char *bat1_name  = "ARUN*";
    const char *bat1_score = "47";
    const char *bat2_label = "BAT 2";
    const char *bat2_name  = "JAKE";
    const char *bat2_score = "12";

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);

        // --- BAT 1 (left half, centred at x=32) ---

        // Label: "BAT 1" = 5*7 = 35px, start at 32 - 17 = 15
        DrawText(canvas, font_label, 15, 12, white, nullptr, bat1_label, 0);

        // Name: "ARUN*" = 5*7 = 35px, start at 32 - 17 = 15
        DrawText(canvas, font_label, 15, 25, blue, nullptr, bat1_name, 0);

        // Score: 2 digits, 25px each = 50px, start at 32 - 25 = 7
        int b1_width = strlen(bat1_score) * 25;
        DrawText(canvas, font_number, 32 - b1_width / 2, 60, white, nullptr, bat1_score, 0);

        // --- BAT 2 (right half, centred at x=160) ---

        // Label: "BAT 2" = 5*7 = 35px, start at 160 - 17 = 143
        DrawText(canvas, font_label, 143, 12, white, nullptr, bat2_label, 0);

        // Name: "JAKE" = 4*7 = 28px, start at 160 - 14 = 146
        DrawText(canvas, font_label, 146, 25, blue, nullptr, bat2_name, 0);

        // Score: 2 digits, 25px each = 50px, start at 160 - 25 = 135
        int b2_width = strlen(bat2_score) * 25;
        DrawText(canvas, font_number, 160 - b2_width / 2, 60, white, nullptr, bat2_score, 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
