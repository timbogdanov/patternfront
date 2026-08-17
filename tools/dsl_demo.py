#!/usr/bin/env python3
"""
Exercise every primitive in the Pattern Forge parametric DSL and prove the claims
docs/03-ai-integration.md makes about it.

For each example program this checks:
  * it renders without error,
  * the result fits the OpenFront format limits (docs/01 §2),
  * it encodes to valid patternData under 1403 chars,
  * seam score is 0 / "Seamless" when autoSize is on (the tiling guarantee, doc 03 §4.5),
  * ink coverage is in a sane band (doc 03 §8's silent-failure check).

Also writes a contact sheet PNG so the output can actually be looked at.

Run:  python3 tools/dsl_demo.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dsl_prototype import (  # noqa: E402
    MAX_B64, MAX_H, MAX_W, MIN_H, MIN_W,
    encode, render, seam_label, seam_scores, tiles_exactly, write_png,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "assets")


def prog(shape, canvas=None, layers=None, post=None):
    return {
        "canvas": canvas or {"width": 32, "height": 32, "scale": 1, "autoSize": True},
        "layers": layers or [{"op": "set", "shape": shape}],
        "post": post or {},
    }


# Every primitive, plus the composite examples from docs/03 §4.6 and §4.7.
GALLERY = [
    ("stripes_v", "vertical stripes",
     prog({"type": "stripes", "axis": "v", "period": 8, "thickness": 4})),
    ("stripes_h", "horizontal stripes",
     prog({"type": "stripes", "axis": "h", "period": 6, "thickness": 3})),
    ("diagonal", "diagonal stripes, thin gap  (doc 03 §4.6)",
     prog({"type": "diagonal", "dx": 1, "dy": 1, "period": 8, "thickness": 5})),
    ("diagonal_steep", "steep diagonal, dx=2",
     prog({"type": "diagonal", "dx": 2, "dy": 1, "period": 8, "thickness": 3})),
    ("checker", "checkerboard",
     prog({"type": "checker", "cellW": 4, "cellH": 4})),
    ("checker_tall", "checker, 3 wide x 5 tall",
     prog({"type": "checker", "cellW": 3, "cellH": 5})),
    ("grid", "grid / graph paper",
     prog({"type": "grid", "periodX": 8, "periodY": 8, "lineX": 1, "lineY": 1})),
    ("dots", "dots",
     prog({"type": "dots", "periodX": 8, "periodY": 8, "radius": 2})),
    ("dots_brick", "dots, offset rows",
     prog({"type": "dots", "periodX": 8, "periodY": 8, "radius": 2, "rowOffset": 4})),
    ("dots_sparse", "sparse scattered dots",
     prog({"type": "dots", "periodX": 12, "periodY": 12, "radius": 2,
           "shape": "diamond", "rowOffset": 6})),
    ("brick", "brick wall",
     prog({"type": "brick", "brickW": 8, "brickH": 4, "mortar": 1, "offset": 4})),
    ("wave", "waves",
     prog({"type": "wave", "axis": "h", "period": 16, "amplitude": 3, "thickness": 2})),
    ("zigzag", "zigzag",
     prog({"type": "zigzag", "axis": "h", "period": 8, "amplitude": 3, "thickness": 2})),
    ("triangles", "triangles",
     prog({"type": "triangles", "size": 8})),
    ("rings", "concentric rings",
     prog({"type": "rings", "period": 16, "thickness": 2})),
    ("halftone", "halftone, 50%",
     prog({"type": "halftone", "period": 8, "level": 0.5})),
    ("halftone_45", "halftone, 45 degrees",
     prog({"type": "halftone", "period": 8, "level": 0.35, "angle": 45})),
    ("noise", "white noise, 35%",
     prog({"type": "noise", "density": 0.35, "seed": 7},
          canvas={"width": 16, "height": 16, "scale": 1, "autoSize": False})),
    ("noise_blue", "blue-ish noise",
     prog({"type": "noise", "density": 0.6, "seed": 3, "blue": True},
          canvas={"width": 16, "height": 16, "scale": 1, "autoSize": False})),
    ("text", "text: KDR",
     prog({"type": "text", "glyphs": "KDR", "font": "5x7", "tracking": 1})),
    ("text_small", "text: OF, 3x5",
     prog({"type": "text", "glyphs": "OF", "font": "3x5", "tracking": 1})),
    ("border", "border / frame",
     prog({"type": "border", "inset": 2, "thickness": 1},
          canvas={"width": 16, "height": 16, "scale": 1, "autoSize": False})),
    ("solid", "solid",
     prog({"type": "solid"},
          canvas={"width": 8, "height": 8, "scale": 3, "autoSize": False})),
    # composites
    ("chainlink", "chain link fence  (doc 03 §4.7)",
     prog(None, layers=[
         {"op": "set", "shape": {"type": "diagonal", "dx": 1, "dy": 1,
                                 "period": 8, "thickness": 2}},
         {"op": "union", "shape": {"type": "diagonal", "dx": 1, "dy": -1,
                                   "period": 8, "thickness": 2}}])),
    ("plaid", "plaid (stripes xor stripes)",
     prog(None, layers=[
         {"op": "set", "shape": {"type": "stripes", "axis": "v",
                                 "period": 8, "thickness": 3}},
         {"op": "xor", "shape": {"type": "stripes", "axis": "h",
                                 "period": 6, "thickness": 2}}])),
    ("dotted_grid", "grid minus dots",
     prog(None, layers=[
         {"op": "set", "shape": {"type": "grid", "periodX": 8, "periodY": 8,
                                 "lineX": 2, "lineY": 2}},
         {"op": "subtract", "shape": {"type": "dots", "periodX": 8, "periodY": 8,
                                      "radius": 1}}])),
    ("houndstooth", "diagonal ∩ checker",
     prog(None, layers=[
         {"op": "set", "shape": {"type": "checker", "cellW": 4, "cellH": 4}},
         {"op": "xor", "shape": {"type": "diagonal", "dx": 1, "dy": 1,
                                 "period": 8, "thickness": 4}}])),
    ("inverted_waves", "waves, inverted",
     prog({"type": "wave", "axis": "v", "period": 12, "amplitude": 2,
           "thickness": 3}, post={"invert": True})),
]


def contact_sheet(results, path, cell_px=6, repeats=3, pad=10, label_h=14):
    """Draw every pattern tiled `repeats`x`repeats` into one PNG."""
    cols = 5
    rows = (len(results) + cols - 1) // cols
    tile_w = max(r["w"] for r in results) * repeats * cell_px
    tile_h = max(r["h"] for r in results) * repeats * cell_px
    cw, ch = tile_w + pad * 2, tile_h + pad * 2 + label_h
    W, H = cols * cw, rows * ch

    BG, INK, PAPER, LBL = (24, 24, 27), (240, 240, 245), (63, 63, 70), (140, 140, 150)
    canvas = [bytearray(BG * W) for _ in range(H)]

    def put(x, y, rgb):
        if 0 <= x < W and 0 <= y < H:
            canvas[y][x * 3:x * 3 + 3] = bytes(rgb)

    from dsl_prototype import FONT_3X5

    def text(x0, y0, s, rgb):
        for i, chn in enumerate(s.upper()[:26]):
            g = FONT_3X5.get(chn)
            if g is None:
                continue
            for r in range(5):
                for c in range(3):
                    if (g[r] >> (2 - c)) & 1:
                        put(x0 + i * 4 + c, y0 + r, rgb)

    for idx, res in enumerate(results):
        gx, gy = (idx % cols) * cw, (idx // cols) * ch
        w, h, buf = res["w"], res["h"], res["buf"]
        for ty in range(h * repeats):
            for tx in range(w * repeats):
                v = buf[(ty % h) * w + (tx % w)]
                rgb = INK if v == 0 else PAPER          # bit 0 == primary
                for py in range(cell_px):
                    for px in range(cell_px):
                        put(gx + pad + tx * cell_px + px,
                            gy + pad + ty * cell_px + py, rgb)
        text(gx + pad, gy + pad + tile_h + 4, res["name"][:26], LBL)

    write_png(path, W, H, canvas)
    return W, H


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    results, failures = [], []

    print(f"{'name':<16}{'W×H':>8}{'sc':>4}{'ink%':>7}{'period':>9}{'tiles':>7}"
          f"{'b64':>6}  status")
    print("-" * 88)

    for name, desc, program in GALLERY:
        try:
            w, h, scale, buf = render(program)
        except Exception as exc:                                   # noqa: BLE001
            failures.append((name, f"render error: {exc}"))
            print(f"{name:<16}  RENDER ERROR: {exc}")
            continue

        b64 = encode(w, h, scale, buf)
        ink = 100.0 * sum(buf) / len(buf)
        exact, px, py = tiles_exactly(program, w, h)

        problems = []
        if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
            problems.append(f"dims {w}x{h} out of range")
        if len(b64) > MAX_B64:
            problems.append(f"b64 {len(b64)} > {MAX_B64}")
        # The real guarantee (doc 03 §4.5): under autoSize the canvas must be a
        # whole number of periods. This is structural, not a measurement.
        if program["canvas"].get("autoSize", True) and not exact:
            problems.append(f"autoSize but {w}x{h} is not a multiple of {px}x{py}")
        if not (5.0 <= ink <= 95.0) and program["layers"][0]["shape"]["type"] != "solid":
            problems.append(f"ink {ink:.1f}% degenerate")

        status = "ok" if not problems else "; ".join(problems)
        if problems:
            failures.append((name, status))

        print(f"{name:<16}{f'{w}×{h}':>8}{scale:>4}{ink:>6.1f}%{f'{px}×{py}':>9}"
              f"{('yes' if exact else 'NO'):>7}{len(b64):>6}  {status}")

        results.append({"name": name, "desc": desc, "w": w, "h": h,
                        "buf": buf, "b64": b64, "scale": scale,
                        "tiles": exact, "ink": ink})

    print("-" * 88)
    print(f"{len(results)}/{len(GALLERY)} rendered, {len(failures)} problem(s)")
    print(f"tiles exactly: {sum(1 for r in results if r['tiles'])}/{len(results)}")

    # ---- the bitmap heuristic, for patterns with no generating function -----
    # Hand-drawn and diffusion output have no declared period, so they need the
    # heuristic scorer. It must stay quiet on good patterns and fire on bad ones;
    # both directions are tested here, because a metric that never fires and a
    # metric that always fires are equally useless.
    from dsl_prototype import _hash2

    def blank(w, h):
        return [0] * (w * h)

    print("\nheuristic scorer — POSITIVE controls (must read Seamless):")
    pos, neg_missed, pos_missed = [], [], []

    # A correctly tiling periodic pattern: stripes period 8 on width 32.
    p1 = [1 if (x % 8) < 4 else 0 for y in range(16) for x in range(32)]
    pos.append(("stripes_p8_w32", 32, 16, p1))
    # Checkerboard, cell 4, width 32.
    p2 = [1 if ((x // 4) + (y // 4)) % 2 else 0 for y in range(16) for x in range(32)]
    pos.append(("checker_c4_w32", 32, 16, p2))
    # Unstructured noise — no rhythm to break.
    p3 = [1 if _hash2(x, y, 42) < 0.4 else 0 for y in range(16) for x in range(32)]
    pos.append(("white_noise", 32, 16, p3))

    for cname, cw, ch, cbuf in pos:
        sh, sv = seam_scores(cw, ch, cbuf)
        v = seam_label(sh, sv)
        ok = v == "Seamless"
        if not ok:
            pos_missed.append(cname)
        print(f"  {cname:<24} {sh:>6.2f}/{sv:<6.2f} {v:<13} "
              f"{'ok' if ok else 'FALSE POSITIVE — too strict'}")

    print("\nheuristic scorer — NEGATIVE controls (must NOT read Seamless):")
    neg = []
    # 1. Broken cadence: period 7 stripes on a 32-wide canvas. The edge itself
    #    looks normal; the stripe SPACING is wrong across the wrap.
    n1 = [1 if (x % 7) < 3 else 0 for y in range(16) for x in range(32)]
    neg.append(("stripes_p7_w32", 32, 16, n1))
    # 2. Classic off-by-one: correct stripes with the final column duplicated.
    n2 = blank(32, 16)
    for y in range(16):
        for x in range(32):
            # col 31 repeats col 0's value, stretching the wrap stripe to 5 wide
            src = x if x < 31 else 0
            n2[y * 32 + x] = 1 if (src % 8) < 4 else 0
    neg.append(("duplicated_edge_col", 32, 16, n2))
    # 3. A stray line of ink down the right edge only.
    n3 = [1 if ((x % 8) < 4 or x == 31) else 0 for y in range(16) for x in range(32)]
    neg.append(("stray_edge_line", 32, 16, n3))
    # 4. Density gradient — smooth inside, jumps across the wrap.
    n4 = [1 if _hash2(x, y, 5) < (x / 32) else 0 for y in range(16) for x in range(32)]
    neg.append(("density_gradient", 32, 16, n4))

    for cname, cw, ch, cbuf in neg:
        sh, sv = seam_scores(cw, ch, cbuf)
        v = seam_label(sh, sv)
        caught = v != "Seamless"
        if not caught:
            neg_missed.append(cname)
        print(f"  {cname:<24} {sh:>6.2f}/{sv:<6.2f} {v:<13} "
              f"{'caught' if caught else 'MISSED — too permissive'}")

    failures.extend((n, "false positive on a good pattern") for n in pos_missed)
    failures.extend((n, "negative control not caught") for n in neg_missed)

    sheet = os.path.join(OUT_DIR, "dsl-gallery.png")
    dims = contact_sheet(results, sheet)
    print(f"\ncontact sheet: {sheet}  ({dims[0]}×{dims[1]})")

    print(f"largest patternData: {max(len(r['b64']) for r in results)} chars "
          f"(limit {MAX_B64})")

    if failures:
        print("\nFAILURES:")
        for n, why in failures:
            print(f"  {n}: {why}")
        return 1
    print("\nALL DSL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
