#!/usr/bin/env python3
"""
Generate the oracle for map-scale sampling, and prove it against an independent
implementation.

WHY THIS EXISTS
---------------
OpenFront paints a pattern onto territory in ABSOLUTE world coordinates, so what
a player sees depends on where the territory sits on the map. `tools/preview_
prototype.py` establishes the sampling rule and verifies it; this turns that into
a fixture the editor's JavaScript can be held to, the same way
`tests/fixtures/codec.json` holds the codec.

Two decisions worth knowing:

  * **Coordinates are written out, not seeded.** The prototype picks probes with
    an LCG whose step is `(1103515245 * s + 12345) & 0x7FFFFFFF`. Reproducing
    that in JavaScript needs `Math.imul`, because `1103515245 * 2**31` is past
    `Number.MAX_SAFE_INTEGER` and a plain multiply silently loses low bits — the
    exact class of bug this fixture exists to catch. Emitting the coordinates
    removes the risk instead of testing around it.

  * **No pattern here comes from the game.** The 31 real patterns are CC BY-SA
    4.0 and are deliberately not redistributed (see NOTICE). Most cases are
    synthesised, because the committed corpus is 1,117 patterns at scale 0 and
    one or two at each of the rest — it was built for width, height and bit
    packing, and scale is the whole variable here. A slice of that corpus still
    rides along, so this decoder is also held against data a different generator
    committed.

Every probe set deliberately straddles the origin. JavaScript's `%` is a
remainder whose sign follows the dividend, so a naive `(x >> scale) % width`
returns a negative index for negative world coordinates and reads before the
start of the array. The world-offset control makes that reachable by panning
left, so the fixture must be able to see it.

    python3 tools/gen-sampler-fixtures.py           # write + verify
    python3 tools/gen-sampler-fixtures.py --check   # verify only, no write
"""

from __future__ import annotations

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                       # for dsl_prototype.encode
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, "tests", "fixtures", "codec.json")
OUT = os.path.join(ROOT, "tests", "fixtures", "sampler.json")

# Enough to catch an off-by-one in any dimension, small enough to read as a diff.
CASES_PER_SCALE = 6
PROBE_SPAN = 4096


def floor_mod(a: int, n: int) -> int:
    return a - n * (a // n)


class Pattern:
    """Decoded pattern. Mirrors OpenFront's PatternDecoder."""

    def __init__(self, pattern_data: str):
        by = base64.urlsafe_b64decode(pattern_data + "=" * (-len(pattern_data) % 4))
        self.scale = by[1] & 0x07
        self.width = (((by[2] & 0x03) << 5) | ((by[1] >> 3) & 0x1F)) + 2
        self.height = ((by[2] >> 2) & 0x3F) + 2
        self._bytes = by

    def is_primary(self, world_x: int, world_y: int) -> bool:
        px = floor_mod(world_x >> self.scale, self.width)
        py = floor_mod(world_y >> self.scale, self.height)
        idx = py * self.width + px
        return (self._bytes[3 + (idx >> 3)] & (1 << (idx & 7))) == 0


def oracle_is_primary(pattern_data: str, wx: int, wy: int) -> bool:
    """
    Decode to a plain grid and sample it by a different route.

    Written deliberately unlike `Pattern.is_primary` — unpacking every bit up
    front and indexing a nested list — so that a shared mistake is unlikely. A
    self-consistent bug is exactly what an oracle has to catch.
    """
    by = base64.urlsafe_b64decode(pattern_data + "=" * (-len(pattern_data) % 4))
    scale = by[1] & 0x07
    w = (((by[2] & 0x03) << 5) | ((by[1] >> 3) & 0x1F)) + 2
    h = ((by[2] >> 2) & 0x3F) + 2
    grid = [[False] * w for _ in range(h)]
    for i in range(w * h):
        bit = (by[3 + (i // 8)] >> (i % 8)) & 1
        grid[i // w][i % w] = bit == 0            # bit 0 means primary
    block = 1 << scale
    # Divide rather than shift, and use Python's floor semantics explicitly.
    cell_x = wx // block
    cell_y = wy // block
    return grid[cell_y % h][cell_x % w]


def probes() -> list[list[int]]:
    """
    World coordinates to sample. Three bands, each for a different failure.

      * A dense block straddling the origin, where the floor-modulo trap lives.
      * Far negatives, where a remainder-based implementation reads out of range.
      * Far positives, which is the only region OpenFront itself ever visits.
    """
    pts: list[list[int]] = []
    for y in range(-9, 10):
        for x in range(-9, 10):
            pts.append([x, y])
    step = 7                                       # coprime with every width here
    for i in range(400):
        pts.append([-PROBE_SPAN + i * step, -PROBE_SPAN + i * step * 3 % 991])
    for i in range(400):
        pts.append([i * step * 5 % PROBE_SPAN, i * step * 11 % PROBE_SPAN])
    return pts


# Bit patterns whose sampling breaks in different ways: a checker catches an
# x/y transposition, the two stripe directions catch it independently, a lone set
# bit catches an index that is off by one anywhere, and its inverse catches a
# polarity flip.
MOTIFS = {
    "checker": lambda x, y, w, h: (x + y) % 2,
    "stripes_v": lambda x, y, w, h: x % 2,
    "stripes_h": lambda x, y, w, h: y % 2,
    "diagonal": lambda x, y, w, h: 1 if (x - y) % 4 < 2 else 0,
    "one-bit": lambda x, y, w, h: 1 if (x, y) == (w - 1, h - 1) else 0,
    "all-but-one": lambda x, y, w, h: 0 if (x, y) == (0, 0) else 1,
}

# Sizes chosen either side of a byte boundary and at both format limits.
SIZES = [(2, 2), (3, 5), (8, 8), (17, 9), (33, 16), (129, 65)]


def pick_cases(corpus: list[dict]) -> list[dict]:
    """
    Patterns to sample, covering every scale.

    The committed corpus is 1,117 patterns at scale 0 and one or two at each of
    the rest — it was built to exercise width, height and bit packing, and scale
    is barely represented. Scale is the whole variable here, since it decides how
    many world tiles share a pattern pixel, so these are synthesised across all
    eight of them. Encoding goes through the DSL prototype's encoder rather than a
    second copy written for this file.

    A slice of the corpus rides along, so the fixture also proves this decoder
    agrees with data that was committed by a different generator.
    """
    from dsl_prototype import encode

    chosen: list[dict] = []
    for scale in range(8):
        for i, (w, h) in enumerate(SIZES):
            name, fn = list(MOTIFS.items())[(scale + i) % len(MOTIFS)]
            bits = [fn(x, y, w, h) for y in range(h) for x in range(w)]
            chosen.append({
                "name": f"{name}-{w}x{h}-s{scale}",
                "patternData": encode(w, h, scale, bits),
                "width": w, "height": h, "scale": scale,
            })

    from_corpus = sorted(corpus, key=lambda p: p["name"])
    stride = max(1, len(from_corpus) // 8)
    chosen += from_corpus[::stride][:8]
    return chosen


def main() -> int:
    check_only = "--check" in sys.argv
    corpus = json.load(open(CORPUS, encoding="utf-8"))["patterns"]
    pts = probes()
    cases = []
    mismatches = 0

    for p in pick_cases(corpus):
        pat = Pattern(p["patternData"])
        bits = []
        for wx, wy in pts:
            got = pat.is_primary(wx, wy)
            if got != oracle_is_primary(p["patternData"], wx, wy):
                print(f"  [FAIL] {p['name']} at ({wx},{wy}): sampler and oracle disagree")
                mismatches += 1
            bits.append("1" if got else "0")
        cases.append({
            "name": p["name"],
            "patternData": p["patternData"],
            "width": pat.width,
            "height": pat.height,
            "scale": pat.scale,
            "expect": "".join(bits),
        })

    if mismatches:
        print(f"\n*** {mismatches} sampler/oracle mismatch(es) — not writing ***")
        return 1

    doc = {
        "note": ("Map-scale sampling oracle. Probes straddle the origin because "
                 "JavaScript's % is a remainder, not a floor modulo. Patterns are "
                 "from the licence-clean corpus, not OpenFront's cosmetics.json."),
        "probeCount": len(pts),
        "caseCount": len(cases),
        "probes": pts,
        "cases": cases,
    }

    if check_only:
        if not os.path.exists(OUT):
            print(f"{OUT} is missing — run without --check")
            return 1
        on_disk = json.load(open(OUT, encoding="utf-8"))
        if on_disk != doc:
            print(f"{OUT} is stale — re-run without --check")
            return 1
        print(f"sampler fixtures current  "
              f"{len(cases)} patterns × {len(pts)} probes, oracle agrees")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    neg = sum(1 for x, y in pts if x < 0 or y < 0)
    print(f"wrote {OUT}")
    print(f"  {len(cases)} patterns × {len(pts)} probes  "
          f"({neg} of them negative), scales {sorted({c['scale'] for c in cases})}")
    print(f"  sampler agrees with the independent oracle on every probe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
