#!/usr/bin/env python3
"""
Draw the PATTERNFRONT wordmark that the editor opens on.

The editor used to boot showing OpenFront's own wordmark. That is their mark,
and this project does not redistribute third-party branding — see NOTICE. So we
draw our own, in the same 1-bit idiom, through the same verified codec: the
wordmark IS an OpenFront pattern, so it round-trips through `encodeOF` exactly
like every stamp does.

Letters are composed from a 5x7 pixel font rather than typed as one big block of
ASCII, so the spacing is consistent and the thing is editable.

    python3 tools/gen-wordmark.py           # report + preview PNG
    python3 tools/gen-wordmark.py --emit    # print the JS constant
"""

from __future__ import annotations

import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PREVIEW = os.path.join(ROOT, "docs", "assets", "wordmark.png")

WORD = "PATTERNFRONT"
MARGIN = 2      # blank pixels around the text
TRACK = 1       # pixels between letters

# 5x7. Only the glyphs PATTERNFRONT needs.
FONT: dict[str, list[str]] = {
    "P": ["####.",
          "#...#",
          "#...#",
          "####.",
          "#....",
          "#....",
          "#...."],
    "A": [".###.",
          "#...#",
          "#...#",
          "#####",
          "#...#",
          "#...#",
          "#...#"],
    "T": ["#####",
          "..#..",
          "..#..",
          "..#..",
          "..#..",
          "..#..",
          "..#.."],
    "E": ["#####",
          "#....",
          "#....",
          "####.",
          "#....",
          "#....",
          "#####"],
    "R": ["####.",
          "#...#",
          "#...#",
          "####.",
          "#.#..",
          "#..#.",
          "#...#"],
    "N": ["#...#",
          "##..#",
          "##..#",
          "#.#.#",
          "#..##",
          "#..##",
          "#...#"],
    "F": ["#####",
          "#....",
          "#....",
          "####.",
          "#....",
          "#....",
          "#...."],
    "O": [".###.",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          ".###."],
}

GLYPH_W, GLYPH_H = 5, 7
MAX_W, MAX_H = 129, 65


def compose(word: str) -> list[str]:
    missing = sorted({c for c in word if c not in FONT})
    if missing:
        raise SystemExit(f"no glyph for {missing} — add it to FONT")
    inner = len(word) * GLYPH_W + (len(word) - 1) * TRACK
    width = inner + MARGIN * 2
    blank = "." * width
    rows = [blank] * MARGIN
    for r in range(GLYPH_H):
        line = "." * MARGIN
        for i, ch in enumerate(word):
            line += FONT[ch][r]
            if i != len(word) - 1:
                line += "." * TRACK
        rows.append(line + "." * MARGIN)
    rows += [blank] * MARGIN
    return rows


def encode(rows: list[str], scale: int = 1) -> str:
    """Identical to the editor's encodeOF: 3-byte header, LSB-first bits."""
    h, w = len(rows), len(rows[0])
    if w > MAX_W or h > MAX_H:
        raise SystemExit(f"{w}x{h} exceeds the {MAX_W}x{MAX_H} limit")
    raw = bytearray(3 + ((w * h + 7) // 8))
    raw[1] = (scale & 7) | (((w - 2) & 31) << 3)
    raw[2] = (((w - 2) >> 5) & 3) | (((h - 2) & 63) << 2)
    for i, bit in enumerate("".join(rows)):
        if bit == "#":
            raw[3 + (i >> 3)] |= 1 << (i & 7)
    return base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


def decode(data: str):
    b = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    scale = b[1] & 7
    w = (((b[2] & 3) << 5) | ((b[1] >> 3) & 31)) + 2
    h = ((b[2] >> 2) & 63) + 2
    bits = [(b[3 + (i >> 3)] >> (i & 7)) & 1 for i in range(w * h)]
    return w, h, scale, bits


def write_png(path: str, w: int, h: int, bits: list[int], zoom: int = 4) -> None:
    import struct
    import zlib
    W, H = w * zoom, h * zoom
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        for x in range(W):
            v = 235 if bits[(y // zoom) * w + (x // zoom)] else 17
            rows += bytes((v, v, v))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
           + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(png)


def main() -> int:
    rows = compose(WORD)
    data = encode(rows)

    w, h, scale, bits = decode(data)
    if encode(rows) != data or (w, h) != (len(rows[0]), len(rows)):
        print("round-trip mismatch")
        return 1
    ink = sum(bits) / (w * h)

    print(f'"{WORD}"  {w}x{h}  scale {scale}  {ink:.0%} ink  '
          f'{len(data)} chars')
    for r in rows:
        print("  " + r.replace("#", "█").replace(".", " "))

    write_png(PREVIEW, w, h, bits)
    print(f"\npreview: {PREVIEW}")

    if "--emit" in sys.argv:
        print("\nconst PATTERNFRONT_WORDMARK=")
        print(f"  '{data}';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
