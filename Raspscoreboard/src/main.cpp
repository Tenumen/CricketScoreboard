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
    Color yellow(255, 255, 0);

    // Example values
    const char *last_inn_runs = "137";
    const char *last_inn_wkts = "11";

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);

        // --- LAST INNINGS (centred across full 192px canvas) ---

        // Label: "LAST INNINGS" = 12*7 = 84px, centre at 96, start at 96 - 42 = 54
        DrawText(canvas, font_label, 54, 12, white, nullptr, "LAST INNINGS", 0);

        // Score: render "137", "/", "11" separately with tighter spacing
        // dejavu-bold-42: ~25px per digit
        // Total: 75 + 15 + 50 = 140px. Centre at 96: start at 96 - 70 = 26
        DrawText(canvas, font_number, 26, 60, yellow, nullptr, last_inn_runs, 0);
        DrawText(canvas, font_label, 103, 48, yellow, nullptr, "/", 0);
        DrawText(canvas, font_number, 112, 60, yellow, nullptr, last_inn_wkts, 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
