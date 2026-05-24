// fireworks.h -- algorithmic full-screen fireworks. Rockets ascend from the
// bottom, burst at apex into a fan of fading particles. StepAndDraw owns
// physics (gravity, life decay) and pixel emission; the caller is
// responsible for clearing the canvas before calling.

#ifndef RASPSCOREBOARD24_EFFECTS_FIREWORKS_H
#define RASPSCOREBOARD24_EFFECTS_FIREWORKS_H

#include <cstdint>
#include <random>
#include <vector>

#include "grid_canvas.h"

namespace cricketboard {

class Fireworks {
public:
    Fireworks();

    // Advance physics by `dt` seconds and emit pixels onto `g`.
    void StepAndDraw(GridCanvas& g, float dt);

private:
    struct Particle {
        float x, y, vx, vy;
        uint8_t r, g, b;
        float life;     // 1.0 -> 0.0 over ~1.7 s
    };
    struct Rocket {
        float x, y, vy;
        uint8_t r, g, b;
        bool alive;
    };

    void SpawnRocket();
    void BurstAt(float x, float y, uint8_t cr, uint8_t cg, uint8_t cb);

    std::vector<Rocket>   rockets_;
    std::vector<Particle> particles_;
    std::mt19937          rng_;
    float                 spawn_accum_;
};

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_EFFECTS_FIREWORKS_H
