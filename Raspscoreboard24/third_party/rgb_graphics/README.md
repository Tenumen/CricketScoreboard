# rgb_graphics (vendored)

`canvas.h`, `graphics.h`, `graphics.cc`, `bdf-font.cc` are copied verbatim from
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix)
(GPLv2). They contain only the pixel-level Canvas interface and BDF font /
text-drawing primitives — **no hardware dependencies**.

These exist so the `headless` build target (`make RENDER_BACKEND=headless`)
can compile on a machine that doesn't have the rpi-rgb-led-matrix library
installed. The HUB75 build path links against `librgbmatrix.a` and uses the
library's own copies of these files instead.

If you need to update them, re-copy from `lib/rpi-rgb-led-matrix/include/` and
`lib/rpi-rgb-led-matrix/lib/`. Both copies must remain in sync — the same
binary will see two different `rgb_matrix::Color` / `Font` / `Canvas`
definitions otherwise, causing ODR violations.
