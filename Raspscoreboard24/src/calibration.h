#ifndef RASPSCOREBOARD24_CALIBRATION_H
#define RASPSCOREBOARD24_CALIBRATION_H

namespace rgb_matrix { class Font; }

namespace cricketboard {

class IDisplay;

enum class CalibrationMode {
    Sequential,  // light each panel in turn (default --calibrate)
    AllAtOnce,   // every panel labelled simultaneously (--calibrate=all)
    Quadrants,   // six 64x64 coloured squares straddling 4-panel junctions
                 // (--calibrate=quads). Verifies col/row mapping is right.
};

// Blocks until `interrupt_flag` becomes true. The caller must have already
// installed SIGINT/SIGTERM handlers that set it.
void RunCalibration(IDisplay *display,
                    const rgb_matrix::Font &label_font,
                    CalibrationMode mode,
                    volatile bool *interrupt_flag);

}  // namespace cricketboard

#endif  // RASPSCOREBOARD24_CALIBRATION_H
