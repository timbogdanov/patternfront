#!/usr/bin/env python3
"""
Reference implementation of map-scale pattern sampling — Phase 3's risky function.

docs/02-architecture.md §3.5 requires ONE implementation of the sampling formula,
shared by the flat preview and the map preview, matching OpenFront's
`PatternDecoder.isPrimary` exactly. Getting this subtly wrong produces a preview
that looks plausible and lies, which is the worst possible failure for a tool whose
whole job is showing you what you'll get.

The three things that are easy to get wrong (docs/01 §4):
  1. sampling uses ABSOLUTE world coordinates, not territory-relative ones,
  2. `>> scale` is applied BEFORE `% width`, not after,
  3. bit 0 means primary, and primary is the TERRITORY colour (secondary = border).

This file implements it once and checks it against all 31 real fixtures.

Run:  python3 tools/preview_prototype.py
"""

from __future__ import annotations

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from dsl_prototype import write_png  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "codec.json")
OUT_DIR = os.path.join(ROOT, "docs", "assets")


# ---------------------------------------------------------------------------
# The decoder + the single sampling function
# ---------------------------------------------------------------------------

def floor_mod(a: int, n: int) -> int:
    """Modulo that is always non-negative — NOT the same as `%` in every language.

    PORTABILITY TRAP for the TypeScript port. JavaScript's `%` is a *remainder*
    whose sign follows the dividend; Python's `%` is a *floor modulo* whose sign
    follows the divisor:

        JS:      -1 % 4  === -1        -9 % 4  === -1
        Python:  -1 %  4  ==  3        -9 %  4  ==  3

    OpenFront itself never hits this — `game.x(tile)` is always >= 0 — so its
    `PatternDecoder` uses a bare `%` safely. Our preview does NOT have that
    guarantee: docs/02 §3.5 gives the user a world-offset control, and panning it
    left produces negative world coordinates. A naive `(x >> scale) % width` in TS
    would then yield a negative index, read past the start of the byte array, and
    render garbage or throw right at the origin.

    So every implementation must route through this helper. In TypeScript:
        const mod = (a: number, n: number) => ((a % n) + n) % n;
    """
    return a - n * (a // n)


class Pattern:
    """Decoded pattern. Mirrors OpenFront's PatternDecoder."""

    def __init__(self, pattern_data: str):
        by = base64.urlsafe_b64decode(pattern_data + "=" * (-len(pattern_data) % 4))
        if len(by) < 3:
            raise ValueError("TruncatedHeader")
        if by[0] != 0:
            raise ValueError(f"UnsupportedVersion {by[0]}")
        b1, b2 = by[1], by[2]
        self.scale = b1 & 0x07
        self.width = (((b2 & 0x03) << 5) | ((b1 >> 3) & 0x1F)) + 2
        self.height = ((b2 >> 2) & 0x3F) + 2
        if len(by) - 3 < (self.width * self.height + 7) >> 3:
            raise ValueError("TruncatedPayload")
        self._bytes = by

    # THE function. Everything that previews a pattern goes through here.
    def is_primary(self, world_x: int, world_y: int) -> bool:
        px = floor_mod(world_x >> self.scale, self.width)
        py = floor_mod(world_y >> self.scale, self.height)
        idx = py * self.width + px
        return (self._bytes[3 + (idx >> 3)] & (1 << (idx & 7))) == 0

    def scaled_width(self) -> int:
        return self.width << self.scale

    def scaled_height(self) -> int:
        return self.height << self.scale


def sample_at(pat: Pattern, world_x: int, world_y: int,
              territory_rgb, border_rgb):
    """Colour of one world tile. Primary -> territory, secondary -> border."""
    return territory_rgb if pat.is_primary(world_x, world_y) else border_rgb


# ---------------------------------------------------------------------------
# Independent oracle: decode to a plain 2-D grid, sample by a different route
# ---------------------------------------------------------------------------

def oracle_grid(pattern_data: str):
    """Build a naive [y][x] grid, then sample it with straightforward arithmetic.

    Deliberately written a different way from Pattern.is_primary so that a shared
    mistake is unlikely — a self-consistent bug is exactly what this must catch.
    """
    by = base64.urlsafe_b64decode(pattern_data + "=" * (-len(pattern_data) % 4))
    scale = by[1] & 0x07
    width = (((by[2] & 0x03) << 5) | ((by[1] >> 3) & 0x1F)) + 2
    height = ((by[2] >> 2) & 0x3F) + 2
    grid = []
    for y in range(height):
        row = []
        for x in range(width):
            i = y * width + x
            byte = by[3 + i // 8]
            row.append((byte // (2 ** (i % 8))) % 2)     # arithmetic, not bitwise
        grid.append(row)

    def sample(wx: int, wy: int) -> bool:
        cell_x = floor_mod(wx // (2 ** scale), width)    # division, not shift
        cell_y = floor_mod(wy // (2 ** scale), height)
        return grid[cell_y][cell_x] == 0

    return sample, width, height, scale


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def lcg(seed: int):
    s = seed & 0xFFFFFFFF
    while True:
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        yield s


def verify(fixtures) -> int:
    print("=== sampleAt vs independent oracle, 31 fixtures ===")
    bad = 0
    for f in fixtures:
        pat = Pattern(f["patternData"])
        oracle, ow, oh, osc = oracle_grid(f["patternData"])

        if (pat.width, pat.height, pat.scale) != (ow, oh, osc):
            print(f"  [FAIL] {f['name']}: header disagreement")
            bad += 1
            continue
        if (pat.width, pat.height, pat.scale) != (f["width"], f["height"], f["scale"]):
            print(f"  [FAIL] {f['name']}: disagrees with fixture header")
            bad += 1
            continue

        rng = lcg(hash(f["name"]) & 0xFFFF)
        mism = 0
        # Cover negatives, the origin, tile boundaries, and far-field coordinates.
        coords = [(0, 0), (-1, -1), (-1, 0), (0, -1),
                  (pat.scaled_width() - 1, pat.scaled_height() - 1),
                  (pat.scaled_width(), pat.scaled_height()),
                  (1 << 20, 1 << 20)]
        for _ in range(10000 - len(coords)):
            coords.append((next(rng) % 4000 - 2000, next(rng) % 4000 - 2000))

        for wx, wy in coords:
            if pat.is_primary(wx, wy) != oracle(wx, wy):
                mism += 1
        if mism:
            print(f"  [FAIL] {f['name']}: {mism} mismatches")
            bad += 1

    print(f"  {len(fixtures) - bad}/{len(fixtures)} fixtures agree "
          f"across ~10,000 world coordinates each (negatives included)")
    return bad


def verify_origin_continuity(fixtures) -> int:
    """The pattern must run continuously through world origin, not glitch at 0.

    This is the check a JS `%` implementation fails. Crossing x = 0, the sampled
    column must simply continue the periodic sequence.
    """
    print("\n=== continuity across world origin (the JS `%` trap) ===")
    bad = 0
    for f in fixtures:
        pat = Pattern(f["patternData"])
        sw = pat.scaled_width()
        ok = True
        for wy in (0, 1, 7):
            for wx in range(-sw, sw):
                # sampling at wx must equal sampling one full period to the right
                if pat.is_primary(wx, wy) != pat.is_primary(wx + sw, wy):
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            print(f"  [FAIL] {f['name']}: discontinuous across the origin")
            bad += 1
    print(f"  {len(fixtures) - bad}/{len(fixtures)} sample continuously "
          f"through negative world coordinates")
    return bad


def verify_matches_openfront_on_nonnegative(fixtures) -> int:
    """Where OpenFront is defined (world coords >= 0), we must match it exactly.

    floor_mod and a bare `%` agree for non-negative inputs, so adding the helper
    must not change behaviour in the range the game actually uses.
    """
    print("\n=== bare `%` and floor_mod agree for all non-negative coords ===")
    bad = 0
    for f in fixtures:
        pat = Pattern(f["patternData"])
        for wy in range(0, 64):
            for wx in range(0, 64):
                naive_x = (wx >> pat.scale) % pat.width
                naive_y = (wy >> pat.scale) % pat.height
                if (naive_x != floor_mod(wx >> pat.scale, pat.width) or
                        naive_y != floor_mod(wy >> pat.scale, pat.height)):
                    bad += 1
                    break
    print(f"  [{'PASS' if not bad else 'FAIL'}] identical over 64x64 tiles "
          f"x {len(fixtures)} fixtures")
    return 1 if bad else 0


def verify_tiling_period(fixtures) -> int:
    """The pattern must repeat exactly every scaledWidth x scaledHeight tiles."""
    print("\n=== tiling period == scaledWidth x scaledHeight ===")
    bad = 0
    for f in fixtures:
        pat = Pattern(f["patternData"])
        sw, sh = pat.scaled_width(), pat.scaled_height()
        ok = True
        for wy in range(0, min(sh, 40)):
            for wx in range(0, min(sw, 40)):
                if pat.is_primary(wx, wy) != pat.is_primary(wx + sw, wy + sh):
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            print(f"  [FAIL] {f['name']}: does not repeat at {sw}x{sh}")
            bad += 1
    print(f"  {len(fixtures) - bad}/{len(fixtures)} repeat exactly at their scaled period")
    return bad


def verify_scale_semantics() -> int:
    """scale must magnify by 2^scale: a block of 2^scale tiles shares one pixel."""
    print("\n=== scale magnifies by 2^scale ===")
    from dsl_prototype import encode
    bad = 0
    for scale in range(4):
        # 2x2 pattern: one primary, three secondary.
        data = encode(2, 2, scale, [0, 1, 1, 1])
        pat = Pattern(data)
        block = 1 << scale
        for wy in range(block):
            for wx in range(block):
                if not pat.is_primary(wx, wy):
                    print(f"  [FAIL] scale {scale}: ({wx},{wy}) should be primary")
                    bad += 1
        if pat.is_primary(block, 0):
            print(f"  [FAIL] scale {scale}: ({block},0) should be secondary")
            bad += 1
        if (pat.scaled_width(), pat.scaled_height()) != (2 * block, 2 * block):
            print(f"  [FAIL] scale {scale}: scaled dims wrong")
            bad += 1
    print(f"  scales 0-3 magnify correctly" if not bad else f"  {bad} failure(s)")
    return bad


def verify_absolute_coords(fixtures) -> int:
    """A territory's on-screen appearance must depend on WHERE it is on the map.

    This is the property a territory-relative implementation silently breaks, so
    test it explicitly: at least one fixture must render differently when the same
    viewport is placed at a different world origin.
    """
    print("\n=== sampling is absolute, not territory-relative ===")
    differing = 0
    for f in fixtures:
        pat = Pattern(f["patternData"])
        a = [pat.is_primary(x, y) for y in range(8) for x in range(8)]
        off = pat.scaled_width() // 2 or 1
        b = [pat.is_primary(x + off, y) for y in range(8) for x in range(8)]
        if a != b:
            differing += 1
    ok = differing > 0
    print(f"  [{'PASS' if ok else 'FAIL'}] {differing}/{len(fixtures)} fixtures render "
          f"differently at a shifted world origin (expected: most)")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Visual: a pattern rendered on a territory silhouette at map scale
# ---------------------------------------------------------------------------

def territory_mask(w: int, h: int):
    """A blobby pseudo-territory so the preview looks like a real map region."""
    import math
    cx, cy = w / 2, h / 2
    mask = []
    for y in range(h):
        row = []
        for x in range(w):
            dx, dy = (x - cx) / (w * 0.42), (y - cy) / (h * 0.42)
            ang = math.atan2(dy, dx)
            wobble = (0.82 + 0.20 * math.sin(ang * 3 + 0.7)
                      + 0.10 * math.sin(ang * 7 - 1.2))
            row.append(math.hypot(dx, dy) < wobble)
        mask.append(row)
    return mask


def render_map_preview(fixtures, path, tile_px=3):
    """Six patterns on identical territories, at their real scale."""
    # Prefer patterns with visible structure at map scale; a solid or empty
    # fill is a valid fixture but renders as a flat block.
    picks = ("alternating", "rows", "cols", "noise")
    chosen = [f for f in fixtures
              if f["name"].startswith(picks) and 8 <= f["width"] <= 40][:6]
    if len(chosen) < 6:
        chosen = fixtures[:6]

    TW, TH = 110, 78                       # territory size in world tiles
    cols, pad, label_h = 3, 8, 14
    cw = TW * tile_px + pad * 2
    ch = TH * tile_px + pad * 2 + label_h
    rows = (len(chosen) + cols - 1) // cols
    W, H = cols * cw, rows * ch

    SEA = (17, 24, 39)
    LAND = (55, 65, 81)                    # unowned land outside the territory
    TERRITORY = (56, 189, 248)             # primary  -> territory colour
    BORDER = (12, 74, 110)                 # secondary -> border colour
    LBL = (148, 163, 184)

    canvas = [bytearray(SEA * W) for _ in range(H)]

    def put(x, y, rgb):
        if 0 <= x < W and 0 <= y < H:
            canvas[y][x * 3:x * 3 + 3] = bytes(rgb)

    from dsl_prototype import FONT_3X5

    def text(x0, y0, s, rgb):
        for i, chn in enumerate(s.upper()[:30]):
            g = FONT_3X5.get(chn)
            if g is None:
                continue
            for r in range(5):
                for c in range(3):
                    if (g[r] >> (2 - c)) & 1:
                        put(x0 + i * 4 + c, y0 + r, rgb)

    mask = territory_mask(TW, TH)

    for idx, f in enumerate(chosen):
        pat = Pattern(f["patternData"])
        gx, gy = (idx % cols) * cw, (idx // cols) * ch
        # World origin differs per cell, which is exactly what absolute
        # coordinates mean: the same pattern phases differently elsewhere.
        ox, oy = idx * 37, idx * 23
        for ty in range(TH):
            for tx in range(TW):
                if mask[ty][tx]:
                    rgb = sample_at(pat, ox + tx, oy + ty, TERRITORY, BORDER)
                else:
                    rgb = LAND
                for py in range(tile_px):
                    for px in range(tile_px):
                        put(gx + pad + tx * tile_px + px,
                            gy + pad + ty * tile_px + py, rgb)
        text(gx + pad, gy + pad + TH * tile_px + 4,
             f"{f['name']} s{pat.scale} {pat.width}x{pat.height}", LBL)

    write_png(path, W, H, canvas)
    return W, H


def main() -> int:
    if not os.path.exists(FIXTURES):
        print("fixtures missing — run tools/gen-codec-fixtures.py first")
        return 2
    fixtures = json.load(open(FIXTURES, encoding="utf-8"))["patterns"]

    bad = 0
    bad += verify(fixtures)
    bad += verify_tiling_period(fixtures)
    bad += verify_scale_semantics()
    bad += verify_absolute_coords(fixtures)
    bad += verify_origin_continuity(fixtures)
    bad += verify_matches_openfront_on_nonnegative(fixtures)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "map-preview.png")
    dims = render_map_preview(fixtures, out)
    print(f"\nmap preview: {out}  ({dims[0]}×{dims[1]})")

    print()
    if bad:
        print(f"*** {bad} FAILURE(S) ***")
        return 1
    print("ALL PREVIEW SAMPLING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
