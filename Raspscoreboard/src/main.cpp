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
    rgb_matrix::Font font_small, font_med, font_large;
    const char *base = "lib/rpi-rgb-led-matrix/fonts/";
    char path[256];

    snprintf(path, sizeof(path), "%s4x6.bdf", base);
    if (!font_small.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    snprintf(path, sizeof(path), "%s6x13.bdf", base);
    if (!font_med.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    snprintf(path, sizeof(path), "%s7x13.bdf", base);
    if (!font_large.LoadFont(path))
        fprintf(stderr, "Warning: could not load font '%s'\n", path);

    int canvas_w = matrix->width();
    int canvas_h = matrix->height();
    printf("Font test running on %dx%d canvas. Press Ctrl+C to exit.\n",
           canvas_w, canvas_h);

    Color white(255, 255, 255);
    Color yellow(255, 255, 0);

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);

        // Left panel (x 0-63): ASTON ON TRENT / C. C.
        // 4x6 font: "ASTON ON TRENT" = 14 chars * 4px = 56px
        DrawText(canvas, font_small, 4, 25, white, nullptr, "ASTON ON TRENT", 0);
        // 6x13 font for "C. C." = 5 chars * 6px = 30px
        DrawText(canvas, font_med, 17, 42, yellow, nullptr, "C. C.", 0);

        // Right panel (x 128-191): MELBOURNE / C. C.
        // 7x13 font: "MELBOURNE" = 9 chars * 7px = 63px
        DrawText(canvas, font_large, 129, 25, white, nullptr, "MELBOURNE", 0);
        // 6x13 font for "C. C."
        DrawText(canvas, font_med, 145, 42, yellow, nullptr, "C. C.", 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
