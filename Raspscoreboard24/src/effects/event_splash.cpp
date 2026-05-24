#include "effects/event_splash.h"

namespace cricketboard {

namespace {

int TextWidth(const rgb_matrix::Font& f, const char* s) {
    int w = 0;
    for (const char* p = s; *p; ++p) {
        w += f.CharacterWidth(static_cast<uint32_t>(*p));
    }
    return w;
}

void DrawCentred(GridCanvas& g, const rgb_matrix::Font& f,
                 int cx, int cy_centre,
                 const rgb_matrix::Color& col, const char* s) {
    const int w          = TextWidth(f, s);
    const int baseline_y = cy_centre + f.baseline() - f.height() / 2;
    rgb_matrix::DrawText(&g, f, cx - w / 2, baseline_y, col, nullptr, s, 0);
}

}  // namespace

void DrawEventSplash(GridCanvas& grid,
                     const rgb_matrix::Font& impact_font,
                     Interlude kind) {
    const int cx = grid.width()  / 2;
    const int cy = grid.height() / 2;

    switch (kind) {
        case Interlude::Wicket:
            DrawCentred(grid, impact_font, cx, cy,
                        rgb_matrix::Color(0xff, 0x44, 0x44), "Wicket!");
            break;
        case Interlude::Four:
            DrawCentred(grid, impact_font, cx, cy,
                        rgb_matrix::Color(0x66, 0xcc, 0xff), "Four!");
            break;
        case Interlude::Six:
            DrawCentred(grid, impact_font, cx, cy,
                        rgb_matrix::Color(0xff, 0xcc, 0x33), "Six!");
            break;
        default:
            break;
    }
}

}  // namespace cricketboard
