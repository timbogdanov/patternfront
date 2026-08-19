#!/usr/bin/env python3
"""
Freeze the parametric DSL into a fixture the editor's JavaScript can be held to.

WHY THIS EXISTS
---------------
`tools/dsl_prototype.py` is the reference implementation of the pattern DSL: 15
primitives, each with a declared period, composed with set/union/intersect/xor/
subtract, sized so the result tiles seamlessly by construction. `tools/dsl_demo.py`
proves 28 programs tile exactly. Both have run on every commit since before the
editor existed, and the editor has never used any of it.

Porting it to JavaScript means two implementations that must agree forever. This
turns the Python one into the oracle, the same way tests/fixtures/codec.json and
tests/fixtures/sampler.json do for the codec and the sampler.

WHAT IT COVERS
--------------
  * The 28 programs from dsl_demo's GALLERY — every primitive, plus the composite
    examples docs/03 §4.6 and §4.7 promise.
  * Each primitive again at non-default parameters, because a port that ignores
    an argument still passes on defaults.
  * Every composition op and every post transform, since those are where an
    off-by-one in a mirror or a rotate hides.

Determinism matters here: `noise` and `dots` jitter both go through the DSL's
`_hash2`, which is written to be stable across languages. If the JavaScript hash
disagrees by one bit, those cases diverge and this fixture says so.

    python3 tools/gen-dsl-fixtures.py           # write + verify
    python3 tools/gen-dsl-fixtures.py --check   # verify only, no write
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "dsl.json")

from dsl_prototype import (encode, render, tiles_exactly,     # noqa: E402
                           seam_scores, seam_label,
                           FONT_5X7, FONT_3X5)
from dsl_demo import GALLERY                                  # noqa: E402


def prog(shape=None, canvas=None, layers=None, post=None) -> dict:
    return {
        "canvas": canvas or {"width": 32, "height": 32, "scale": 1, "autoSize": True},
        "layers": layers or [{"op": "set", "shape": shape}],
        "post": post or {},
    }


# Each primitive away from its defaults. A port that silently drops a parameter
# renders the default and passes the gallery; it fails here.
OFF_DEFAULTS = [
    ("solid_only", {"type": "solid"}),
    ("stripes_thin", {"type": "stripes", "axis": "h", "period": 7, "thickness": 2, "phase": 3}),
    ("diagonal_steep", {"type": "diagonal", "dx": 3, "dy": 2, "period": 12, "thickness": 4, "phase": 5}),
    ("checker_oblong", {"type": "checker", "cellW": 5, "cellH": 2, "phase": 1}),
    ("grid_thick", {"type": "grid", "periodX": 9, "periodY": 6, "lineX": 3, "lineY": 2,
                    "phaseX": 2, "phaseY": 4}),
    ("dots_diamond", {"type": "dots", "periodX": 10, "periodY": 6, "radius": 3,
                      "shape": "diamond", "rowOffset": 5}),
    ("dots_square_jitter", {"type": "dots", "periodX": 8, "periodY": 8, "radius": 2,
                            "shape": "square", "jitter": 2, "seed": 7}),
    ("brick_offset", {"type": "brick", "brickW": 10, "brickH": 5, "mortar": 2, "offset": 3}),
    ("wave_vertical", {"type": "wave", "axis": "v", "period": 14, "amplitude": 4, "thickness": 3,
                       "phase": 2}),
    ("zigzag_vertical", {"type": "zigzag", "axis": "v", "period": 10, "amplitude": 4, "thickness": 3}),
    ("triangles_down", {"type": "triangles", "size": 6, "orientation": "down"}),
    ("rings_offset", {"type": "rings", "period": 12, "thickness": 3, "cx": 4, "cy": 2}),
    ("halftone_45", {"type": "halftone", "period": 10, "level": 0.8, "angle": 45}),
    ("halftone_light", {"type": "halftone", "period": 6, "level": 0.15}),
    ("noise_blue", {"type": "noise", "density": 0.35, "seed": 99, "blue": True}),
    ("noise_plain", {"type": "noise", "density": 0.6, "seed": 12345}),
    ("text_3x5", {"type": "text", "glyphs": "OF", "font": "3x5", "tracking": 2, "leading": 3}),
    ("text_5x7", {"type": "text", "glyphs": "PF9", "font": "5x7", "tracking": 1, "leading": 1}),
    ("border_inset", {"type": "border", "inset": 3, "thickness": 2}),
]

OPS = ["set", "union", "intersect", "xor", "subtract"]
POSTS = [
    ("post_mirrorX", {"mirrorX": True}),
    ("post_mirrorY", {"mirrorY": True}),
    ("post_both_mirrors", {"mirrorX": True, "mirrorY": True}),
    ("post_rot90", {"rotate90": 1}),
    ("post_rot180", {"rotate90": 2}),
    ("post_rot270", {"rotate90": 3}),
    ("post_invert", {"invert": True}),
    ("post_rot90_invert", {"rotate90": 1, "invert": True}),
]


def cases() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for name, _desc, program in GALLERY:
        out.append((f"gallery:{name}", program))
    for name, shape in OFF_DEFAULTS:
        out.append((f"params:{name}", prog(shape)))
    # Composition: the same two shapes under every op, so an op that is wired to
    # the wrong bitwise operator cannot hide behind a shape that rarely overlaps.
    for op in OPS:
        out.append((f"op:{op}", prog(None, layers=[
            {"op": "set", "shape": {"type": "stripes", "axis": "v", "period": 8, "thickness": 5}},
            {"op": op, "shape": {"type": "stripes", "axis": "h", "period": 6, "thickness": 4}},
        ])))
    # Asymmetric source, so a mirror or rotate that is a no-op is visible.
    asym = {"type": "triangles", "size": 5, "orientation": "up"}
    for name, post in POSTS:
        out.append((f"{name}", prog(asym, post=post)))
    # Explicit sizing, where the tiling guarantee is deliberately switched off.
    out.append(("canvas:fixed", prog(
        {"type": "diagonal", "dx": 1, "dy": 1, "period": 7, "thickness": 3},
        canvas={"width": 23, "height": 17, "scale": 3, "autoSize": False})))
    out.append(("canvas:limits", prog(
        {"type": "checker", "cellW": 1, "cellH": 1},
        canvas={"width": 129, "height": 65, "scale": 0, "autoSize": False})))
    return out


def main() -> int:
    check_only = "--check" in sys.argv
    built = []
    tiling_failures = []

    for name, program in cases():
        w, h, scale, buf = render(program)
        data = encode(w, h, scale, buf)
        ok, _px, _py = tiles_exactly(program, w, h)
        if program.get("canvas", {}).get("autoSize", True) and not ok:
            tiling_failures.append(name)
        sh, sv = seam_scores(w, h, buf)
        built.append({
            "name": name,
            "program": program,
            "width": w,
            "height": h,
            "scale": scale,
            "ink": sum(buf),
            "patternData": data,
            # The seam metric, which an earlier revision got wrong for 17 of 28
            # correctly-tiling patterns. Pinning the scores as well as the label
            # means a port that lands on the right verdict by luck still fails.
            "seam": [sh, sv],
            "seamLabel": seam_label(sh, sv),
        })

    if tiling_failures:
        print("*** programs with autoSize that do not tile exactly: "
              f"{', '.join(tiling_failures)} ***")
        return 1

    doc = {
        "note": ("Oracle for the parametric DSL. Rendered by tools/dsl_prototype.py, "
                 "which tools/dsl_demo.py verifies tiles exactly. The editor's "
                 "JavaScript must reproduce patternData byte for byte."),
        "caseCount": len(built),
        # The glyph tables the editor carries a copy of. Transcribing these by
        # hand once put a wrong 'D' in the 5x7 font and rewrote half of 3x5; the
        # text cases caught it, but as "384 lit pixels, oracle says 400", which
        # names the symptom rather than the cause. Comparing the tables directly
        # says which glyph.
        "fonts": {"5x7": FONT_5X7, "3x5": FONT_3X5},
        "cases": built,
    }

    if check_only:
        if not os.path.exists(OUT):
            print(f"{OUT} is missing — run without --check")
            return 1
        if json.load(open(OUT, encoding="utf-8")) != doc:
            print(f"{OUT} is stale — re-run without --check")
            return 1
        print(f"DSL fixtures current  {len(built)} programs, all autoSize cases tile exactly")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    shapes = {c["program"]["layers"][0]["shape"]["type"] for c in built}
    print(f"wrote {OUT}")
    print(f"  {len(built)} programs  {len(shapes)} distinct primitives in the first layer")
    print(f"  every autoSize program tiles exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
