#!/usr/bin/env python3
"""
Reference implementation of the Pattern Forge parametric DSL.

This is the prototype for Engine A (docs/03-ai-integration.md §4) — the engine that
handles geometric prompts without touching a diffusion model. It exists to prove, before
any Laravel or TypeScript is written, that:

  1. all 15 shape primitives render correctly,
  2. every primitive is genuinely periodic and declares its true period,
  3. the LCM sizing rule (doc 03 §4.5) yields seam score 0 by construction,
  4. output encodes to valid OpenFront patternData inside the format limits.

The TypeScript and PHP implementations should be ported from this file.

Run:  python3 tools/dsl_prototype.py
"""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib
from dataclasses import dataclass, field
from math import gcd

# ---------------------------------------------------------------------------
# Format limits (docs/01-pattern-format.md §2)
# ---------------------------------------------------------------------------

MIN_W, MAX_W = 2, 129
MIN_H, MAX_H = 2, 65
MAX_B64 = 1403
MAX_LAYERS = 8


def lcm(a: int, b: int) -> int:
    return a * b // gcd(a, b)


# ---------------------------------------------------------------------------
# Codec (docs/01-pattern-format.md §5) — bit 0 == primary
# ---------------------------------------------------------------------------

def encode(width: int, height: int, scale: int, bits: list[int]) -> str:
    w, h = width - 2, height - 2
    b1 = (scale & 0x07) | ((w & 0x1F) << 3)
    b2 = ((w >> 5) & 0x03) | ((h & 0x3F) << 2)
    payload = bytearray((width * height + 7) >> 3)
    for i, v in enumerate(bits):
        if v:
            payload[i >> 3] |= 1 << (i & 7)
    raw = bytes([0, b1, b2]) + bytes(payload)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# ---------------------------------------------------------------------------
# 5x7 and 3x5 bitmap fonts, MSB-left within each row
# ---------------------------------------------------------------------------

FONT_5X7 = {
    "A": [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "B": [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    "C": [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
    "D": [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
    "E": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
    "F": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    "G": [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F],
    "H": [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "I": [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "J": [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    "M": [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11],
    "N": [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    "O": [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "P": [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    "Q": [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D],
    "R": [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    "S": [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E],
    "T": [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "V": [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
    "W": [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11],
    "X": [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
    "Y": [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
    "Z": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
    "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "2": [0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F],
    "3": [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
    "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
}

FONT_3X5 = {
    "A": [0x2, 0x5, 0x7, 0x5, 0x5], "B": [0x6, 0x5, 0x6, 0x5, 0x6],
    "C": [0x3, 0x4, 0x4, 0x4, 0x3], "D": [0x6, 0x5, 0x5, 0x5, 0x6],
    "E": [0x7, 0x4, 0x6, 0x4, 0x7], "F": [0x7, 0x4, 0x6, 0x4, 0x4],
    "G": [0x3, 0x4, 0x5, 0x5, 0x3], "H": [0x5, 0x5, 0x7, 0x5, 0x5],
    "I": [0x7, 0x2, 0x2, 0x2, 0x7], "J": [0x1, 0x1, 0x1, 0x5, 0x2],
    "K": [0x5, 0x5, 0x6, 0x5, 0x5], "L": [0x4, 0x4, 0x4, 0x4, 0x7],
    "M": [0x5, 0x7, 0x7, 0x5, 0x5], "N": [0x5, 0x7, 0x7, 0x7, 0x5],
    "O": [0x2, 0x5, 0x5, 0x5, 0x2], "P": [0x6, 0x5, 0x6, 0x4, 0x4],
    "Q": [0x2, 0x5, 0x5, 0x6, 0x3], "R": [0x6, 0x5, 0x6, 0x5, 0x5],
    "S": [0x3, 0x4, 0x2, 0x1, 0x6], "T": [0x7, 0x2, 0x2, 0x2, 0x2],
    "U": [0x5, 0x5, 0x5, 0x5, 0x7], "V": [0x5, 0x5, 0x5, 0x5, 0x2],
    "W": [0x5, 0x5, 0x7, 0x7, 0x5], "X": [0x5, 0x5, 0x2, 0x5, 0x5],
    "Y": [0x5, 0x5, 0x2, 0x2, 0x2], "Z": [0x7, 0x1, 0x2, 0x4, 0x7],
    "0": [0x7, 0x5, 0x5, 0x5, 0x7], "1": [0x2, 0x6, 0x2, 0x2, 0x7],
    "2": [0x6, 0x1, 0x2, 0x4, 0x7], "3": [0x6, 0x1, 0x2, 0x1, 0x6],
    "4": [0x5, 0x5, 0x7, 0x1, 0x1], "5": [0x7, 0x4, 0x6, 0x1, 0x6],
    "6": [0x3, 0x4, 0x7, 0x5, 0x7], "7": [0x7, 0x1, 0x2, 0x2, 0x2],
    "8": [0x7, 0x5, 0x7, 0x5, 0x7], "9": [0x7, 0x5, 0x7, 0x1, 0x6],
}


def _hash2(x: int, y: int, seed: int) -> float:
    """Deterministic [0,1) hash. Stable across runs and languages."""
    h = (x * 374761393 + y * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFFFF) / 4294967296.0


# ---------------------------------------------------------------------------
# Shape primitives
#
# Each returns (fn, period_x, period_y) where fn(x, y) -> 0 | 1 and fn is
# genuinely periodic with the declared period. The periods drive the tiling
# guarantee in size_canvas().
# ---------------------------------------------------------------------------

def shape_solid(**_):
    return (lambda x, y: 1), 1, 1


def shape_stripes(axis="v", period=8, thickness=4, phase=0, **_):
    thickness = min(thickness, period - 1)
    if axis == "v":
        return (lambda x, y: 1 if (x + phase) % period < thickness else 0), period, 1
    return (lambda x, y: 1 if (y + phase) % period < thickness else 0), 1, period


def shape_diagonal(dx=1, dy=1, period=8, thickness=4, phase=0, **_):
    """Lines of slope dy/dx. Points on one line satisfy x*dy - y*dx = const.

    True period is period/gcd(dy,period) in x and period/gcd(dx,period) in y —
    tighter than the naive period*dx x period*dy.
    """
    thickness = min(thickness, period - 1)
    px = period // gcd(dy % period or period, period)
    py = period // gcd(dx % period or period, period)

    def fn(x, y):
        return 1 if (x * dy - y * dx + phase) % period < thickness else 0

    return fn, px, py


def shape_checker(cellW=4, cellH=4, phase=0, **_):
    def fn(x, y):
        return 1 if ((x // cellW) + (y // cellH) + phase) % 2 else 0

    return fn, 2 * cellW, 2 * cellH


def shape_grid(periodX=8, periodY=8, lineX=1, lineY=1, phaseX=0, phaseY=0, **_):
    lineX, lineY = min(lineX, periodX - 1), min(lineY, periodY - 1)

    def fn(x, y):
        return 1 if ((x + phaseX) % periodX < lineX or
                     (y + phaseY) % periodY < lineY) else 0

    return fn, periodX, periodY


def shape_dots(periodX=8, periodY=8, radius=2, shape="circle",
               rowOffset=0, jitter=0, seed=0, **_):
    doubled = rowOffset % periodX != 0
    py = periodY * 2 if doubled else periodY

    def fn(x, y):
        row = y // periodY
        ox = (row * rowOffset) % periodX
        cx = (x - ox) % periodX - periodX / 2.0
        cy = y % periodY - periodY / 2.0
        if jitter:
            j = _hash2(x // periodX, row, seed)
            cx += (j - 0.5) * 2 * jitter
            cy += (_hash2(row, x // periodX, seed + 1) - 0.5) * 2 * jitter
        if shape == "square":
            d = max(abs(cx), abs(cy))
        elif shape == "diamond":
            d = abs(cx) + abs(cy)
        else:
            d = math.hypot(cx, cy)
        return 1 if d <= radius else 0

    return fn, periodX, py


def shape_brick(brickW=8, brickH=4, mortar=1, offset=4, **_):
    def fn(x, y):
        row = y // brickH
        xs = (x + row * offset) % brickW
        return 1 if (y % brickH < mortar or xs < mortar) else 0

    return fn, lcm(brickW, brickW // gcd(offset % brickW or brickW, brickW)), 2 * brickH


def shape_wave(axis="h", period=16, amplitude=3, thickness=2, phase=0, **_):
    vp = max(2 * amplitude, thickness + 1)

    def fn(x, y):
        if axis == "h":
            off = round(amplitude * math.sin(2 * math.pi * ((x + phase) % period) / period))
            return 1 if (y - off) % vp < thickness else 0
        off = round(amplitude * math.sin(2 * math.pi * ((y + phase) % period) / period))
        return 1 if (x - off) % vp < thickness else 0

    return (fn, period, vp) if axis == "h" else (fn, vp, period)


def shape_zigzag(axis="h", period=8, amplitude=3, thickness=2, **_):
    vp = max(2 * amplitude, thickness + 1)

    def tri(t):
        half = period / 2.0
        u = t % period
        return round(amplitude * (2 * abs(u / half - 1) - 1))

    def fn(x, y):
        if axis == "h":
            return 1 if (y - tri(x)) % vp < thickness else 0
        return 1 if (x - tri(y)) % vp < thickness else 0

    return (fn, period, vp) if axis == "h" else (fn, vp, period)


def shape_triangles(size=8, orientation="up", **_):
    def fn(x, y):
        u = x % (2 * size)
        v = y % size
        if orientation == "down":
            v = size - 1 - v
        half = size - 1 - v
        return 1 if (half <= u < 2 * size - half) else 0

    return fn, 2 * size, size


def shape_rings(period=16, thickness=2, cx=0, cy=0, **_):
    def fn(x, y):
        u = (x + cx) % period - period / 2.0
        v = (y + cy) % period - period / 2.0
        d = int(math.hypot(u, v))
        return 1 if d % (thickness * 2) < thickness else 0

    return fn, period, period


def shape_halftone(period=8, level=0.5, angle=0, **_):
    r = math.sqrt(max(0.0, min(1.0, level))) * period * 0.62

    def fn(x, y):
        if angle == 45:
            row = y // period
            xs = (x + (row % 2) * (period // 2)) % period
        else:
            xs = x % period
        u = xs - period / 2.0
        v = y % period - period / 2.0
        return 1 if math.hypot(u, v) <= r else 0

    return fn, period, period * (2 if angle == 45 else 1)


def shape_noise(density=0.5, seed=0, blue=False, canvas=(16, 16), **_):
    w, h = canvas
    grid = [[1 if _hash2(x, y, seed) < density else 0
             for x in range(w)] for y in range(h)]
    if blue:
        # Cheap void-and-cluster approximation: drop points with a lit
        # 4-neighbour (toroidally), which breaks up clumps.
        out = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                if not grid[y][x]:
                    continue
                if any(out[(y + dy) % h][(x + dx) % w]
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    continue
                out[y][x] = 1
        grid = out
    return (lambda x, y: grid[y % h][x % w]), w, h


def shape_text(glyphs="AB", font="5x7", tracking=1, leading=2, **_):
    """Repeating text. `leading` is the blank gap between stacked rows — without
    it the rows abut and the result reads as texture rather than lettering."""
    table = FONT_5X7 if font == "5x7" else FONT_3X5
    gw, gh = (5, 7) if font == "5x7" else (3, 5)
    chars = [c for c in glyphs.upper() if c in table][:8] or ["A"]
    total = len(chars) * (gw + tracking)
    vspan = gh + leading

    def fn(x, y):
        v = y % vspan
        if v >= gh:
            return 0                       # inside the leading gap
        u = x % total
        idx = u // (gw + tracking)
        col = u % (gw + tracking)
        if col >= gw or idx >= len(chars):
            return 0
        return 1 if (table[chars[idx]][v] >> (gw - 1 - col)) & 1 else 0

    return fn, total, vspan


def shape_border(inset=0, thickness=1, canvas=(16, 16), **_):
    w, h = canvas

    def fn(x, y):
        u, v = x % w, y % h
        inner = (inset <= u < w - inset) and (inset <= v < h - inset)
        core = (inset + thickness <= u < w - inset - thickness) and \
               (inset + thickness <= v < h - inset - thickness)
        return 1 if (inner and not core) else 0

    return fn, w, h


SHAPES = {
    "solid": shape_solid, "stripes": shape_stripes, "diagonal": shape_diagonal,
    "checker": shape_checker, "grid": shape_grid, "dots": shape_dots,
    "brick": shape_brick, "wave": shape_wave, "zigzag": shape_zigzag,
    "triangles": shape_triangles, "rings": shape_rings, "halftone": shape_halftone,
    "noise": shape_noise, "text": shape_text, "border": shape_border,
}

# Shapes whose period is defined by the canvas rather than their own parameters.
CANVAS_LOCKED = {"noise", "border"}


# ---------------------------------------------------------------------------
# Validation (docs/03-ai-integration.md §4.4)
# ---------------------------------------------------------------------------

RANGES = {
    "period": (2, 64), "periodX": (2, 64), "periodY": (2, 64),
    "thickness": (1, 63), "phase": (0, 63), "phaseX": (0, 63), "phaseY": (0, 63),
    "dx": (1, 8), "dy": (1, 8), "cellW": (1, 32), "cellH": (1, 32),
    "lineX": (1, 8), "lineY": (1, 8), "radius": (0, 16), "rowOffset": (0, 63),
    "jitter": (0, 4), "brickW": (2, 64), "brickH": (1, 32), "mortar": (1, 4),
    "offset": (0, 63), "amplitude": (1, 16), "size": (2, 32),
    "cx": (0, 63), "cy": (0, 63), "level": (0.0, 1.0), "density": (0.0, 1.0),
    "inset": (0, 16), "tracking": (0, 3), "leading": (0, 8),
}


class DslError(Exception):
    pass


def validate_shape(raw: dict) -> dict:
    if not isinstance(raw, dict) or "type" not in raw:
        raise DslError("shape missing 'type'")
    t = raw["type"]
    if t not in SHAPES:
        raise DslError(f"unknown shape type {t!r}")
    out = {"type": t}
    for k, v in raw.items():
        if k == "type":
            continue
        if k in RANGES:
            lo, hi = RANGES[k]
            out[k] = max(lo, min(hi, v))          # clamp, don't reject
        else:
            out[k] = v                             # enums / strings / seeds
    if "thickness" in out and "period" in out:
        out["thickness"] = min(out["thickness"], out["period"] - 1)
    if "seed" in out:
        out["seed"] = int(out["seed"]) & 0xFFFFFFFF
    if t == "text":
        g = "".join(c for c in str(out.get("glyphs", "A")).upper()
                    if c.isalnum())[:8]
        out["glyphs"] = g or "A"
    return out


def validate_program(prog: dict) -> dict:
    if not isinstance(prog, dict):
        raise DslError("program must be an object")
    layers = prog.get("layers") or []
    if not layers:
        raise DslError("program has no layers")
    if len(layers) > MAX_LAYERS:
        raise DslError(f"too many layers ({len(layers)} > {MAX_LAYERS})")
    clean = {
        "canvas": dict(prog.get("canvas") or {}),
        "layers": [{"op": l.get("op", "union"), "shape": validate_shape(l["shape"])}
                   for l in layers],
        "post": dict(prog.get("post") or {}),
    }
    clean["layers"][0]["op"] = "set"
    return clean


# ---------------------------------------------------------------------------
# Sizing — the tiling guarantee (docs/03-ai-integration.md §4.5)
# ---------------------------------------------------------------------------

def size_canvas(program: dict) -> tuple[int, int]:
    canvas = program.get("canvas", {})
    want_w = canvas.get("width", 16)
    want_h = canvas.get("height", 16)
    if not canvas.get("autoSize", True):
        return (max(MIN_W, min(MAX_W, want_w)), max(MIN_H, min(MAX_H, want_h)))

    px = py = 1
    for layer in program["layers"]:
        s = layer["shape"]
        if s["type"] in CANVAS_LOCKED:
            continue
        _, sx, sy = SHAPES[s["type"]](**{k: v for k, v in s.items() if k != "type"},
                                      canvas=(want_w, want_h))
        px, py = lcm(px, max(1, sx)), lcm(py, max(1, sy))

    def fit(period, want, lo, hi):
        if period > hi:
            return hi                       # cannot tile; caller reports a seam
        n = max(1, round(want / period))
        size = period * n
        while size > hi:
            size -= period
        while size < lo:
            size += period
        return size

    return fit(px, want_w, MIN_W, MAX_W), fit(py, want_h, MIN_H, MAX_H)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render(program: dict) -> tuple[int, int, int, list[int]]:
    program = validate_program(program)
    w, h = size_canvas(program)
    scale = max(0, min(7, program.get("canvas", {}).get("scale", 1)))

    buf = [0] * (w * h)
    for layer in program["layers"]:
        s = layer["shape"]
        fn, _, _ = SHAPES[s["type"]](**{k: v for k, v in s.items() if k != "type"},
                                     canvas=(w, h))
        op = layer["op"]
        for y in range(h):
            base = y * w
            for x in range(w):
                v = fn(x, y)
                i = base + x
                if op == "set":
                    buf[i] = v
                elif op == "union":
                    buf[i] |= v
                elif op == "intersect":
                    buf[i] &= v
                elif op == "xor":
                    buf[i] ^= v
                elif op == "subtract":
                    buf[i] &= 1 - v

    post = program.get("post", {})
    if post.get("mirrorX"):
        buf = [buf[y * w + (w - 1 - x)] for y in range(h) for x in range(w)]
    if post.get("mirrorY"):
        buf = [buf[(h - 1 - y) * w + x] for y in range(h) for x in range(w)]
    for _ in range(post.get("rotate90", 0) % 4):
        buf = [buf[(h - 1 - x) * w + y] for y in range(w) for x in range(h)]
        w, h = h, w
    if post.get("invert"):
        buf = [1 - v for v in buf]

    return w, h, scale, buf


# ---------------------------------------------------------------------------
# Seam scoring (docs/03-ai-integration.md §6.1)
# ---------------------------------------------------------------------------

def _percentile(values: list[int], q: float) -> float:
    """Linear-interpolated percentile, q in [0,1]."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def tiles_exactly(program: dict, w: int, h: int) -> tuple[bool, int, int]:
    """STRUCTURAL tiling check for DSL output — exact, not heuristic.

    For a program we know each primitive's true period analytically, so we do not
    need to measure the rendered bitmap at all: the pattern tiles perfectly iff the
    canvas is a whole number of periods in both axes. This is what doc 03 §4.5
    means by "seamless by construction" — assert the construction, don't score it.

    Returns (tiles, period_x, period_y).
    """
    program = validate_program(program)
    px = py = 1
    for layer in program["layers"]:
        s = layer["shape"]
        if s["type"] in CANVAS_LOCKED:
            continue                      # locked to the canvas, tiles trivially
        _, sx, sy = SHAPES[s["type"]](**{k: v for k, v in s.items() if k != "type"},
                                      canvas=(w, h))
        px, py = lcm(px, max(1, sx)), lcm(py, max(1, sy))
    rot = program.get("post", {}).get("rotate90", 0) % 4
    if rot % 2:
        px, py = py, px
    return (w % px == 0 and h % py == 0), px, py


def dominant_period(w: int, h: int, buf: list[int], axis: str,
                    limit: int | None = None) -> tuple[int, float]:
    """Smallest shift under which the bitmap best repeats, plus its error rate.

    `limit` restricts detection to the leading `limit` columns/rows. Detecting the
    intrinsic rhythm on the interior only keeps an edge defect from corrupting the
    very measurement meant to expose it.
    """
    span = w if axis == "x" else h
    scan = min(span, limit or span)
    best_p, best_err = span, 1.0
    for p in range(2, span // 2 + 1):
        bad = tot = 0
        if axis == "x":
            for x in range(scan - p):
                for y in range(h):
                    tot += 1
                    bad += buf[y * w + x] != buf[y * w + x + p]
        else:
            for y in range(scan - p):
                for x in range(w):
                    tot += 1
                    bad += buf[y * w + x] != buf[(y + p) * w + x]
        if tot == 0:
            continue
        err = bad / tot
        if err < best_err - 1e-9:
            best_err, best_p = err, p
    return best_p, best_err


def toroidal_error(w: int, h: int, buf: list[int], axis: str, p: int) -> float:
    """How badly the pattern breaks period `p` once it is tiled (wrapped)."""
    bad = tot = 0
    if axis == "x":
        for x in range(w):
            for y in range(h):
                tot += 1
                bad += buf[y * w + x] != buf[y * w + (x + p) % w]
    else:
        for y in range(h):
            for x in range(w):
                tot += 1
                bad += buf[y * w + x] != buf[((y + p) % h) * w + x]
    return bad / tot if tot else 0.0


def _rhythm_penalty(w: int, h: int, buf: list[int], axis: str) -> float:
    """Detect a rhythm that tiling breaks.

    Local adjacency at the wrap cannot see this: period-7 stripes on a 32-wide
    canvas produce a perfectly ordinary-looking edge, and a duplicated final
    column puts the defect one pixel *inside* the wrap. Both destroy the cadence.

    So: recover the intrinsic period from the interior, then ask whether the
    tiled pattern still honours it.
    """
    span = w if axis == "x" else h
    if span < 6:
        return 0.0
    p, err_interior = dominant_period(w, h, buf, axis, limit=max(4, span * 3 // 4))
    if err_interior >= PERIODIC_EPS:
        return 0.0                      # not periodic enough for rhythm to apply
    if span % p != 0:
        return RHYTHM_PENALTY           # cadence cannot survive tiling at all
    err_tiled = toroidal_error(w, h, buf, axis, p)
    if err_tiled > err_interior + PERIODIC_EPS:
        return RHYTHM_PENALTY           # periodic inside, broken across the wrap
    return 0.0


# A pattern this close to perfectly periodic is treated as periodic, and its
# rhythm must survive tiling.
PERIODIC_EPS = 0.02
RHYTHM_PENALTY = 3.0


def seam_scores(w: int, h: int, buf: list[int]) -> tuple[float, float]:
    """Rank the wrap edge against the pattern's own interior edges.

    A correctly-tiling periodic pattern legitimately has a hard transition at the
    wrap — vertical stripes of period 8 on a width-32 canvas put a stripe boundary
    exactly there. What makes a seam *visible* is the wrap being an OUTLIER, i.e.
    more discontinuous than the pattern's own internal transitions ever get.

    So compare the wrap's difference count against the 90th percentile of all
    interior adjacent-pair difference counts. ~1.0 means "as discontinuous as a
    normal internal edge" = invisible. Much above 1.0 means a real seam.

    Using a high percentile rather than the mean is the crux: the mean is dragged
    down by the many identical column pairs inside a periodic pattern, which makes
    every legitimate boundary look like a defect.
    """
    px = lambda x, y: buf[y * w + x]

    col_diffs = [sum(1 for y in range(h) if px(x, y) != px(x + 1, y))
                 for x in range(w - 1)]
    wrap_h = sum(1 for y in range(h) if px(w - 1, y) != px(0, y))
    ref_h = _percentile(col_diffs, 0.90)
    score_h = 0.0 if wrap_h == 0 else wrap_h / max(ref_h, 1.0)

    row_diffs = [sum(1 for x in range(w) if px(x, y) != px(x, y + 1))
                 for y in range(h - 1)]
    wrap_v = sum(1 for x in range(w) if px(x, h - 1) != px(x, 0))
    ref_v = _percentile(row_diffs, 0.90)
    score_v = 0.0 if wrap_v == 0 else wrap_v / max(ref_v, 1.0)

    # Rhythm check. Local adjacency alone cannot see a broken *cadence*: stripes
    # of period 7 on a 32-wide canvas produce a perfectly ordinary-looking
    # transition at the wrap, but the stripe spacing is wrong there. If the bitmap
    # is strongly periodic and the canvas is not a whole number of periods, the
    # rhythm breaks on tiling regardless of how the edge itself looks.
    score_h = max(score_h, _rhythm_penalty(w, h, buf, "x"))
    score_v = max(score_v, _rhythm_penalty(w, h, buf, "y"))

    return score_h, score_v


def seam_label(sh: float, sv: float) -> str:
    worst = max(sh, sv)
    return "Seamless" if worst <= 1.3 else ("Slight seam" if worst <= 2.0
                                            else "Visible seam")


# ---------------------------------------------------------------------------
# PNG output (no third-party dependencies)
# ---------------------------------------------------------------------------

def write_png(path: str, width: int, height: int, rows: list[bytearray]) -> None:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
