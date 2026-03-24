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
    matrix_options.chain_length = 1;    // Single panel for initial test
    matrix_options.parallel = 1;        // Single chain for initial test
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

    printf("Test pattern running on 64x64 panel. Press Ctrl+C to exit.\n");

    Color white(255, 255, 255);
    Color red(255, 0, 0);
    Color green(0, 200, 0);
    Color blue(0, 0, 255);
    Color yellow(255, 255, 0);

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);  // Clear to black

        // -----------------------------------------------------------------
        // Test pattern: border, corner markers, coordinate labels, crosshair
        // -----------------------------------------------------------------

        // Draw border (1 px) in white
        for (int x = 0; x < 64; x++) {
            canvas->SetPixel(x, 0, 255, 255, 255);   // Top edge
            canvas->SetPixel(x, 63, 255, 255, 255);   // Bottom edge
        }
        for (int y = 0; y < 64; y++) {
            canvas->SetPixel(0, y, 255, 255, 255);    // Left edge
            canvas->SetPixel(63, y, 255, 255, 255);   // Right edge
        }

        // Corner markers (4x4 blocks) — each corner a different colour
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                canvas->SetPixel(1 + i, 1 + j, 255, 0, 0);       // Top-left: RED
                canvas->SetPixel(60 + i, 1 + j, 0, 200, 0);      // Top-right: GREEN
                canvas->SetPixel(1 + i, 60 + j, 0, 0, 255);      // Bottom-left: BLUE
                canvas->SetPixel(60 + i, 60 + j, 255, 255, 0);   // Bottom-right: YELLOW
            }
        }

        // Centre crosshair
        for (int i = 28; i < 36; i++) {
            canvas->SetPixel(i, 31, 255, 255, 255);  // Horizontal
            canvas->SetPixel(i, 32, 255, 255, 255);
            canvas->SetPixel(31, i, 255, 255, 255);  // Vertical
            canvas->SetPixel(32, i, 255, 255, 255);
        }

        // Corner labels
        DrawText(canvas, font, 6, 12, red, nullptr, "TL", 0);
        DrawText(canvas, font, 46, 12, green, nullptr, "TR", 0);
        DrawText(canvas, font, 6, 62, blue, nullptr, "BL", 0);
        DrawText(canvas, font, 46, 62, yellow, nullptr, "BR", 0);

        // Centre label with panel dimensions
        DrawText(canvas, font, 8, 28, white, nullptr, "64x64", 0);
        DrawText(canvas, font, 12, 42, white, nullptr, "TEST", 0);

        // Swap the off-screen canvas to display (vsync'd)
        canvas = matrix->SwapOnVSync(canvas);

        // Static image — no need for fast updates
        usleep(500 * 1000);  // 500 ms
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
