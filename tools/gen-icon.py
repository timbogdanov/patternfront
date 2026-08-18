#!/usr/bin/env python3
"""
Draw the application icon.

The icon is the editor's own subject matter: a 1-bit tiling pattern, rendered
big. It is generated rather than hand-painted so it stays consistent with the
artwork the app makes, and so there is no binary blob in the repo that nobody
can regenerate.

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
GRID = 16            # the icon is a 16x16 pattern, blown up
CELL = SIZE // GRID

# Aseprite's palette, which is the app's own chrome.
INK = (0xE6, 0xE6, 0xE8)
PAPER = (0x20, 0x21, 0x25)
ACCENT = (0x29, 0x62, 0xFF)

# A "P" that also reads as a tiling motif: the counter and the stem give it
# structure at 16px, and it still resolves at 32px in a taskbar.
ART = [
    "................",
    "..############..",
    "..############..",
    "..####....####..",
    "..####....####..",
    "..####....####..",
    "..####....####..",
    "..############..",
    "..############..",
    "..####..........",
    "..####..........",
    "..####..........",
    "..####..........",
    "..####..........",
    "..####..........",
    "................",
]


def png(path: str, width: int, height: int, pixel) -> None:
    rows = bytearray()
    for y in range(height):
        rows.append(0)                      # filter: none
        for x in range(width):
            rows += bytes(pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(blob)


def main() -> int:
    if len(ART) != GRID or any(len(r) != GRID for r in ART):
        print(f"ART must be {GRID}x{GRID}")
        return 1

    # A thin accent rule along the bottom, the way the editor marks the active
    # thing. Keeps the icon from being two flat greys.
    rule_top = SIZE - CELL // 2

    def pixel(x: int, y: int):
        if y >= rule_top:
            return ACCENT
        return INK if ART[y // CELL][x // CELL] == "#" else PAPER

    png(OUT, SIZE, SIZE, pixel)
    print(f"wrote {OUT}  ({SIZE}x{SIZE}, {os.path.getsize(OUT):,} bytes)")
    for r in ART:
        print("  " + r.replace("#", "██").replace(".", "  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
