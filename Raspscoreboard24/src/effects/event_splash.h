// event_splash.h -- text-only "Wicket!" / "Four!" / "Six!" splashes. The
// caller fills the canvas first; this just paints the centred label.

#ifndef RASPSCOREBOARD24_EFFECTS_EVENT_SPLASH_H
#define RASPSCOREBOARD24_EFFECTS_EVENT_SPLASH_H

#include "effects/event_detect.h"
#include "graphics.h"
#include "grid_canvas.h"

namespace cricketboard {

void DrawEventSplash(GridCanvas& grid,
                     const rgb_matrix::Font& impact_font,
                     Interlude kind);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_EFFECTS_EVENT_SPLASH_H
