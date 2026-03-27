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

    // Load a font for text rendering
    rgb_matrix::Font font;
    const char *font_path = "lib/rpi-rgb-led-matrix/fonts/7x13.bdf";
    if (!font.LoadFont(font_path)) {
        fprintf(stderr, "Warning: could not load font '%s'. Text will not render.\n", font_path);
    }

    int canvas_w = matrix->width();   // 192 for 3 chained 64x64
    int canvas_h = matrix->height();  // 64
    printf("Test pattern running on %dx%d canvas. Press Ctrl+C to exit.\n",
           canvas_w, canvas_h);

    Color white(255, 255, 255);
    Color red(255, 0, 0);
    Color green(0, 200, 0);
    Color blue(0, 0, 255);
    Color yellow(255, 255, 0);
    Color cyan(0, 200, 200);
    Color magenta(200, 0, 200);
    Color grey(100, 100, 100);

    // Panel colours for identification
    Color panel_colors[3] = { red, green, blue };
    const char *panel_names[3] = { "PANEL 1", "PANEL 2", "PANEL 3" };

    while (!interrupt_received) {
        canvas->Fill(0, 0, 0);  // Clear to black

        // -----------------------------------------------------------------
        // Test pattern: outer border, per-panel borders and labels,
        // corner markers, canvas dimensions
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

        // Per-panel dividers and labels
        for (int p = 0; p < 3; p++) {
            int x_off = p * 64;

            // Vertical divider at panel boundary (except left edge of panel 0)
            if (p > 0) {
                for (int y = 0; y < canvas_h; y++) {
                    canvas->SetPixel(x_off - 1, y, 100, 100, 100);
                    canvas->SetPixel(x_off, y, 100, 100, 100);
                }
            }

            // Panel number label (centred in each panel)
            DrawText(canvas, font, x_off + 8, 35, panel_colors[p], nullptr, panel_names[p], 0);

            // Coloured bar along top of each panel (2px high, inset)
            for (int x = x_off + 2; x < x_off + 62; x++) {
                canvas->SetPixel(x, 2, panel_colors[p].r, panel_colors[p].g, panel_colors[p].b);
                canvas->SetPixel(x, 3, panel_colors[p].r, panel_colors[p].g, panel_colors[p].b);
            }

            // Coloured bar along bottom of each panel
            for (int x = x_off + 2; x < x_off + 62; x++) {
                canvas->SetPixel(x, 60, panel_colors[p].r, panel_colors[p].g, panel_colors[p].b);
                canvas->SetPixel(x, 61, panel_colors[p].r, panel_colors[p].g, panel_colors[p].b);
            }
        }

        // Corner markers (4x4 blocks)
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                canvas->SetPixel(1 + i, 5 + j, 255, 0, 0);
                canvas->SetPixel(canvas_w - 5 + i, 5 + j, 0, 200, 0);
                canvas->SetPixel(1 + i, canvas_h - 9 + j, 0, 0, 255);
                canvas->SetPixel(canvas_w - 5 + i, canvas_h - 9 + j, 255, 255, 0);
            }
        }

        // Canvas dimensions centred at bottom
        char dims[32];
        snprintf(dims, sizeof(dims), "%dx%d", canvas_w, canvas_h);
        DrawText(canvas, font, 76, 55, white, nullptr, dims, 0);

        // Physical wiring hint
        DrawText(canvas, font, 4, 20, grey, nullptr, "Pi->", 0);

        canvas = matrix->SwapOnVSync(canvas);
        usleep(500 * 1000);
    }

    // Clean up
    matrix->Clear();
    delete matrix;
    printf("\nDone.\n");
    return 0;
}
