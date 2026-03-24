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
    matrix_options.chain_length = 2;    // Two panels daisy-chained
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

    // Load a font for text rendering
    rgb_matrix::Font font;
    const char *font_path = "lib/rpi-rgb-led-matrix/fonts/7x13.bdf";
    if (!font.LoadFont(font_path)) {
        fprintf(stderr, "Warning: could not load font '%s'. Text will not render.\n", font_path);
    }

    int canvas_w = matrix->width();   // 128 for 2 chained 64x64
    int canvas_h = matrix->height();  // 64
    printf("Test pattern running on %dx%d canvas. Press Ctrl+C to exit.\n",
           canvas_w, canvas_h);

    Color white(255, 255, 255);
    Color red(255, 0, 0);
    Color green(0, 200, 0);
    Color blue(0, 0, 255);
    Color yellow(255, 255, 0);
    Color cyan(0, 200, 200);

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);  // Clear to black

        // -----------------------------------------------------------------
        // Test pattern: outer border, per-panel borders, corner markers,
        // panel numbers, centre crosshair
        // -----------------------------------------------------------------

        // Outer border (full canvas)
        for (int x = 0; x < canvas_w; x++) {
            canvas->SetPixel(x, 0, 255, 255, 255);
            canvas->SetPixel(x, canvas_h - 1, 255, 255, 255);
        }
        for (int y = 0; y < canvas_h; y++) {
            canvas->SetPixel(0, y, 255, 255, 255);
            canvas->SetPixel(canvas_w - 1, y, 255, 255, 255);
        }

        // Per-panel vertical divider
        for (int y = 0; y < canvas_h; y++) {
            canvas->SetPixel(63, y, 100, 100, 100);
            canvas->SetPixel(64, y, 100, 100, 100);
        }

        // Corner markers (4x4 blocks)
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                canvas->SetPixel(1 + i, 1 + j, 255, 0, 0);                    // TL: RED
                canvas->SetPixel(canvas_w - 5 + i, 1 + j, 0, 200, 0);         // TR: GREEN
                canvas->SetPixel(1 + i, canvas_h - 5 + j, 0, 0, 255);         // BL: BLUE
                canvas->SetPixel(canvas_w - 5 + i, canvas_h - 5 + j, 255, 255, 0); // BR: YELLOW
            }
        }

        // Corner labels
        DrawText(canvas, font, 6, 12, red, nullptr, "TL", 0);
        DrawText(canvas, font, canvas_w - 20, 12, green, nullptr, "TR", 0);
        DrawText(canvas, font, 6, canvas_h - 2, blue, nullptr, "BL", 0);
        DrawText(canvas, font, canvas_w - 20, canvas_h - 2, yellow, nullptr, "BR", 0);

        // Panel number labels
        DrawText(canvas, font, 20, 35, white, nullptr, "PANEL 1", 0);
        DrawText(canvas, font, 84, 35, cyan, nullptr, "PANEL 2", 0);

        // Canvas dimensions
        char dims[32];
        snprintf(dims, sizeof(dims), "%dx%d", canvas_w, canvas_h);
        DrawText(canvas, font, 44, 55, white, nullptr, dims, 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
