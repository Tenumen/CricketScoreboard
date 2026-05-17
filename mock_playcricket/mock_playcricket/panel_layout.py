"""Python mirror of Raspscoreboard24/src/panel_layout.h.

KEEP IN SYNC with the C++ header. If you edit one, edit both. The C++ side
maps logical->hardware coords in GridCanvas::SetPixel; this file does the
inverse to render what the audience would see.
"""
from __future__ import annotations

PANEL_PX       = 64
GRID_COLS      = 6
GRID_ROWS      = 4
LOGICAL_WIDTH  = GRID_COLS * PANEL_PX     # 384
LOGICAL_HEIGHT = GRID_ROWS * PANEL_PX     # 256

CHAIN_LENGTH    = 8
PARALLEL_CHAINS = 3
HARDWARE_WIDTH  = CHAIN_LENGTH * PANEL_PX     # 512
HARDWARE_HEIGHT = PARALLEL_CHAINS * PANEL_PX  # 192

PAR_BOTTOM = 2
PAR_MIDDLE = 1
PAR_TOP    = 0

# layout[row][col] = (parallel, chain_pos, rotation) — matches kPanelLayout in C++.
# Row 0=A (top), 3=D (bottom). Col 0=audience-left, 5=audience-right.
LAYOUT = [
    # Row A
    [(PAR_BOTTOM, 1, 0), (PAR_BOTTOM, 2, 0), (PAR_BOTTOM, 3, 0),
     (PAR_BOTTOM, 4, 0), (PAR_BOTTOM, 5, 0), (PAR_BOTTOM, 6, 0)],
    # Row B
    [(PAR_BOTTOM, 0, 0), (PAR_MIDDLE, 0, 0), (PAR_MIDDLE, 3, 0),
     (PAR_MIDDLE, 4, 0), (PAR_MIDDLE, 7, 0), (PAR_BOTTOM, 7, 0)],
    # Row C
    [(PAR_TOP,    0, 0), (PAR_MIDDLE, 1, 0), (PAR_MIDDLE, 2, 0),
     (PAR_MIDDLE, 5, 0), (PAR_MIDDLE, 6, 0), (PAR_TOP,    7, 0)],
    # Row D
    [(PAR_TOP,    1, 0), (PAR_TOP,    2, 0), (PAR_TOP,    3, 0),
     (PAR_TOP,    4, 0), (PAR_TOP,    5, 0), (PAR_TOP,    6, 0)],
]


def hardware_to_logical(buf: bytes, hw_w: int, hw_h: int) -> bytes:
    """Take a hardware-mapped 512x192 RGB frame and reverse-map it back to the
    audience-view 384x256 logical canvas. Per-panel rotation is undone."""
    from PIL import Image
    if hw_w != HARDWARE_WIDTH or hw_h != HARDWARE_HEIGHT:
        # Best-effort: if dimensions don't match, just resize fit and skip mapping
        src = Image.frombytes("RGB", (hw_w, hw_h), bytes(buf))
        dst = src.resize((LOGICAL_WIDTH, LOGICAL_HEIGHT))
        return dst.tobytes()
    src = Image.frombytes("RGB", (hw_w, hw_h), bytes(buf))
    dst = Image.new("RGB", (LOGICAL_WIDTH, LOGICAL_HEIGHT))
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            parallel, chain_pos, rotation = LAYOUT[r][c]
            x0 = chain_pos * PANEL_PX
            y0 = parallel  * PANEL_PX
            tile = src.crop((x0, y0, x0 + PANEL_PX, y0 + PANEL_PX))
            if rotation == 180:
                tile = tile.rotate(180)
            dst.paste(tile, (c * PANEL_PX, r * PANEL_PX))
    return dst.tobytes()
