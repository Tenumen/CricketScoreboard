#include "effects/fireworks.h"

#include <algorithm>
#include <cmath>

namespace cricketboard {

namespace {

constexpr int   kCanvasW       = 384;
constexpr int   kCanvasH       = 256;
constexpr float kGravity       = 90.f;     // px/s^2
constexpr float kRocketVy      = -180.f;   // px/s (negative = upward)
constexpr float kSpawnEvery    = 0.55f;    // seconds between rocket spawns
constexpr int   kMaxRockets    = 6;
constexpr int   kMaxParticles  = 400;
constexpr float kParticleDecay = 0.6f;     // life lost per second

constexpr uint8_t kPalette[][3] = {
    {255, 215,  60},   // gold
    {255, 100, 100},   // red
    {120, 220, 255},   // cyan
    {120, 255, 130},   // green
    {255, 130, 220},   // magenta
    {255, 255, 255},   // white
};
constexpr int kPaletteN = sizeof(kPalette) / sizeof(kPalette[0]);

void Put(GridCanvas& g, int x, int y, uint8_t r, uint8_t gn, uint8_t b) {
    if (x < 0 || x >= kCanvasW || y < 0 || y >= kCanvasH) return;
    g.SetPixel(x, y, r, gn, b);
}

}  // namespace

Fireworks::Fireworks()
    : rng_(std::random_device{}()), spawn_accum_(0.f) {
    rockets_.reserve(kMaxRockets);
    particles_.reserve(kMaxParticles);
}

void Fireworks::SpawnRocket() {
    if (rockets_.size() >= static_cast<size_t>(kMaxRockets)) return;
    std::uniform_int_distribution<int> x_dist(40, kCanvasW - 40);
    std::uniform_int_distribution<int> pal_dist(0, kPaletteN - 1);
    Rocket r{};
    r.x  = static_cast<float>(x_dist(rng_));
    r.y  = static_cast<float>(kCanvasH - 1);
    r.vy = kRocketVy;
    const auto& c = kPalette[pal_dist(rng_)];
    r.r = c[0]; r.g = c[1]; r.b = c[2];
    r.alive = true;
    rockets_.push_back(r);
}

void Fireworks::BurstAt(float x, float y, uint8_t cr, uint8_t cg, uint8_t cb) {
    std::uniform_int_distribution<int>    count_dist(60, 90);
    std::uniform_real_distribution<float> theta_dist(0.f, 6.2831853f);
    std::uniform_real_distribution<float> speed_dist(40.f, 80.f);
    const int wanted    = count_dist(rng_);
    const int headroom  = kMaxParticles - static_cast<int>(particles_.size());
    const int n         = std::min(wanted, std::max(0, headroom));
    for (int i = 0; i < n; ++i) {
        const float theta = theta_dist(rng_);
        const float speed = speed_dist(rng_);
        Particle p{};
        p.x  = x;
        p.y  = y;
        p.vx = std::cos(theta) * speed;
        p.vy = std::sin(theta) * speed;
        p.r  = cr; p.g = cg; p.b = cb;
        p.life = 1.f;
        particles_.push_back(p);
    }
}

void Fireworks::StepAndDraw(GridCanvas& canvas, float dt) {
    // Cap dt so an idle stall doesn't teleport every particle off-screen.
    if (dt > 0.1f) dt = 0.1f;

    spawn_accum_ += dt;
    while (spawn_accum_ >= kSpawnEvery) {
        spawn_accum_ -= kSpawnEvery;
        SpawnRocket();
    }

    for (auto& r : rockets_) {
        if (!r.alive) continue;
        r.y  += r.vy * dt;
        r.vy += kGravity * dt;
        Put(canvas, static_cast<int>(r.x), static_cast<int>(r.y), r.r, r.g, r.b);
        // Burst at apex (vy >= 0) or near the top of the canvas.
        if (r.vy >= 0.f || r.y < 40.f) {
            BurstAt(r.x, r.y, r.r, r.g, r.b);
            r.alive = false;
        }
    }
    rockets_.erase(
        std::remove_if(rockets_.begin(), rockets_.end(),
                       [](const Rocket& r){ return !r.alive; }),
        rockets_.end());

    for (auto& p : particles_) {
        p.x    += p.vx * dt;
        p.y    += p.vy * dt;
        p.vy   += kGravity * dt;
        p.life -= dt * kParticleDecay;
        if (p.life <= 0.f) continue;
        const uint8_t r = static_cast<uint8_t>(p.r * p.life);
        const uint8_t g = static_cast<uint8_t>(p.g * p.life);
        const uint8_t b = static_cast<uint8_t>(p.b * p.life);
        Put(canvas, static_cast<int>(p.x), static_cast<int>(p.y), r, g, b);
    }
    particles_.erase(
        std::remove_if(particles_.begin(), particles_.end(),
                       [](const Particle& p){ return p.life <= 0.f; }),
        particles_.end());
}

}  // namespace cricketboard
