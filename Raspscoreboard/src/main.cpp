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
    matrix_options.hardware_mapping = "regular";  // or "adafruit-hat", "adafruit-hat-pwm"
    matrix_options.rows = 32;           // Panel height in pixels (32 or 64)
    matrix_options.cols = 64;           // Panel width in pixels (32, 64, or 128)
    matrix_options.chain_length = 1;    // Number of panels daisy-chained
    matrix_options.parallel = 1;        // Number of parallel chains (up to 3 on Pi 3)
    matrix_options.brightness = 50;     // 1-100 percent

    rgb_matrix::RuntimeOptions runtime_options;
    runtime_options.gpio_slowdown = 2;  // Increase if you see glitches (1-4)

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

    // Load a font for text rendering
    rgb_matrix::Font font;
    const char *font_path = "lib/rpi-rgb-led-matrix/fonts/7x13.bdf";
    if (!font.LoadFont(font_path)) {
        fprintf(stderr, "Warning: could not load font '%s'. Text will not render.\n", font_path);
    }

    printf("Scoreboard running. Press Ctrl+C to exit.\n");

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);  // Clear to black

        // -----------------------------------------------------------------
        // Draw your scoreboard content here
        // Example: draw a static score string
        // -----------------------------------------------------------------
        Color white(255, 255, 255);
        Color red(255, 0, 0);
        Color green(0, 200, 0);

        DrawText(canvas, font, 2, 12, white, nullptr, "HOME  AWAY", 0);
        DrawText(canvas, font, 2, 28, green, nullptr, "  3  :  1 ", 0);

        // Swap the off-screen canvas to display (vsync'd)
        canvas = matrix->SwapOnVSync(canvas);

        // Throttle the update loop
        usleep(50 * 1000);  // 50 ms → ~20 fps
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
