#!/usr/bin/env python3
"""
Draw the application icon.

The icon is the editor's own subject matter: a 1-bit tiling pattern, rendered
big. It is generated rather than hand-painted so it stays consistent with the
artwork the app makes, and so there is no binary blob in the repo that nobody
can regenerate.

Three things the icon has to do, in order:

  * Sit correctly in a Dock. macOS icons are a superellipse — the "squircle" —
    on a transparent field, not a full-bleed square. An app that ships a square
    reads as unfinished next to everything Apple ships. The tile here is 824 of
    1024 px, which is Apple's own proportion, and the corner is a real
    superellipse rather than a rounded rectangle, which is visibly different at
    this size.

  * Say what the app is. A bare letterform says "some app starting with P". A
    tiling pattern says "this makes patterns", and the diagonal used here is a
    pattern the editor actually ships.

  * Survive 16px. Everything is on an 8-cell grid with no detail finer than one
    cell, so the motif holds together in a Finder list or a taskbar.

The colour tells the same story the app now tells: the pattern is one bit per
pixel, and colour arrives when something paints it. One diagonal band carries
that pattern in duotone, the way the preview shows it; the rest stays in plain
ink, the way the canvas shows it.

electron-builder derives .icns and .ico from this single 1024x1024 PNG, so this
is the only image the build needs.

    python3 tools/gen-icon.py
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "build", "icon.png")

SIZE = 1024
TILE = 824               # Apple's proportion for the icon body within the canvas
EXPONENT = 5.0           # superellipse power; 5 is close to Apple's squircle
SS = 4                   # supersampling per axis, for a clean tile edge
GRID = 8                 # the motif is an 8x8 pattern, blown up

# The app's own chrome, so the icon and the window agree.
PAPER = (0x20, 0x21, 0x25)      # --well, the editor's background
INK = (0xE6, 0xE6, 0xE8)        # the editor's foreground
ACCENT = (0xE1, 0xB8, 0x5F)     # --accent, the same gold the app selects with
# Inside the band only the *ink* changes colour; the ground stays the same dark as
# everywhere else. Giving the band its own ground introduced a third grey that sat
# between paper and ink and made the whole tile muddy at small sizes.

# A diagonal, which is one of the patterns the editor ships, at the coarsest
# step that still reads as motion. Two cells of ink, two of paper, shifted one
# cell per row — it tiles seamlessly, which is the property the whole app is
# about. Eight cells across means nothing is finer than an eighth of the tile,
# so the motif still holds at 16px.
ART = [
    "".join("#" if ((x - y) % 4) < 2 else "." for x in range(GRID))
    for y in range(GRID)
]

# One stripe carries the duotone. An earlier version coloured half the tile,
# which put colour on the same diagonal as the stripes and turned the whole
# thing to noise at small sizes — the eye had no edge to hold on to. A single
# band leaves the icon reading as a 1-bit pattern with one thing happening in
# it, which is also the honest description of the app.
def in_band(cx: int, cy: int) -> bool:
    return (cx - cy) // 4 == 0


def png(path: str, width: int, height: int, pixel) -> None:
    """Write an 8-bit RGBA PNG. `pixel(x, y)` returns (r, g, b, a)."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)                      # filter: none
        for x in range(width):
            rows += bytes(pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(blob)


def coverage(x: int, y: int, half: float, cx: float) -> float:
    """
    How much of pixel (x, y) falls inside the superellipse, 0..1.

    Sampled rather than solved: the curve has no closed form for pixel area, and
    at SS=4 the error is well under one 8-bit step.
    """
    hits = 0
    for sy in range(SS):
        for sx in range(SS):
            px = (x + (sx + 0.5) / SS - cx) / half
            py = (y + (sy + 0.5) / SS - cx) / half
            if abs(px) ** EXPONENT + abs(py) ** EXPONENT <= 1.0:
                hits += 1
    return hits / (SS * SS)


def main() -> int:
    if len(ART) != GRID or any(len(r) != GRID for r in ART):
        print(f"ART must be {GRID}x{GRID}")
        return 1

    inset = (SIZE - TILE) / 2
    half = TILE / 2
    centre = inset + half
    cell = TILE / GRID

    def pixel(x: int, y: int):
        a = coverage(x, y, half, centre)
        if a <= 0.0:
            return (0, 0, 0, 0)

        # Which pattern cell this pixel belongs to, clamped at the tile edge.
        cx = min(GRID - 1, max(0, int((x - inset) // cell)))
        cy = min(GRID - 1, max(0, int((y - inset) // cell)))
        lit = ART[cy][cx] == "#"

        if lit:
            rgb = ACCENT if in_band(cx, cy) else INK
        else:
            rgb = PAPER

        return (rgb[0], rgb[1], rgb[2], round(a * 255))

    png(OUT, SIZE, SIZE, pixel)
    print(f"wrote {OUT}  ({SIZE}x{SIZE}, {os.path.getsize(OUT):,} bytes)")
    for cy in range(GRID):
        line = ""
        for cx in range(GRID):
            lit = ART[cy][cx] == "#"
            if in_band(cx, cy):
                line += "▓▓" if lit else "░░"
            else:
                line += "██" if lit else "  "
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
