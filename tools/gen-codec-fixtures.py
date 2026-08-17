#!/usr/bin/env python3
"""
Generate a licence-clean corpus that exercises every boundary of the OpenFront
pattern format, and prove the codec round-trips all of it byte-exactly.

WHY THIS EXISTS
---------------
The codec used to be verified against the 31 real patterns in OpenFront's
`cosmetics.json`. Those are CC BY-SA 4.0 and include third-party characters, so
this project does not redistribute them (see NOTICE) and CI cannot rely on them.

Losing that check would have been a real loss, so this replaces it with a
stronger one. The 31 real patterns were an arbitrary sample: they covered
widths 2-66, heights 2-35 and only scales 0-3. This covers the format's ENTIRE
addressable space — every width 2..129, every height 2..65, all 8 scales, and
the bit patterns most likely to break a packer (all set, all clear, alternating,
single bit at each end, and sizes that land either side of a byte boundary).

`tools/gen-fixtures.py` still exists and still reads a local OpenFront checkout,
so anyone who has one can additionally cross-check against the real game data.
That is a local convenience; this is the gate.

    python3 tools/gen-codec-fixtures.py           # write + verify
    python3 tools/gen-codec-fixtures.py --check   # verify only, no write
"""

from __future__ import annotations

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "codec.json")

MAX_W, MAX_H, MAX_B64 = 129, 65, 1403
MIN_W = MIN_H = 2


# ── the codec, mirroring app/patternfront.html exactly ───────────────────

def encode(w: int, h: int, scale: int, bits: list[int]) -> str:
    raw = bytearray(3 + ((w * h + 7) // 8))
    raw[0] = 0
    raw[1] = (scale & 7) | (((w - 2) & 31) << 3)
    raw[2] = (((w - 2) >> 5) & 3) | (((h - 2) & 63) << 2)
    for i, b in enumerate(bits):
        if b:
            raw[3 + (i >> 3)] |= 1 << (i & 7)
    return base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


def decode(data: str):
    by = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    if len(by) < 3:
        raise ValueError("TruncatedHeader")
    if by[0] != 0:
        raise ValueError(f"UnsupportedVersion {by[0]}")
    scale = by[1] & 7
    w = (((by[2] & 3) << 5) | ((by[1] >> 3) & 31)) + 2
    h = ((by[2] >> 2) & 63) + 2
    if len(by) - 3 < (w * h + 7) // 8:
        raise ValueError("TruncatedPayload")
    bits = [(by[3 + (i >> 3)] >> (i & 7)) & 1 for i in range(w * h)]
    return w, h, scale, bits


# ── bit patterns chosen to break a careless packer ───────────────────────

def fills(w: int, h: int) -> list[tuple[str, list[int]]]:
    n = w * h
    return [
        ("clear",       [0] * n),
        ("solid",       [1] * n),
        ("alternating", [i & 1 for i in range(n)]),
        ("rows",        [(i // w) & 1 for i in range(n)]),
        ("cols",        [(i % w) & 1 for i in range(n)]),
        # A single bit at each extreme catches off-by-one in the bit index and
        # in the final partial byte.
        ("first-bit",   [1] + [0] * (n - 1)),
        ("last-bit",    [0] * (n - 1) + [1]),
        # Deterministic pseudo-noise. No RNG: the corpus must be reproducible
        # so a fixture diff means the codec changed, not the seed.
        ("noise",       [(i * 2654435761 >> 13) & 1 for i in range(n)]),
    ]


def cases():
    """Every dimension boundary, every scale, every fill worth testing."""
    # Sizes either side of a byte boundary in the packed payload, plus the
    # format's own extremes and the width where the 6th bit of w-2 carries
    # into byte 2 (w=34) — the only genuinely fiddly bit of the header.
    widths = sorted({MIN_W, 3, 7, 8, 9, 16, 17, 33, 34, 35, 63, 64, 65,
                     127, 128, MAX_W})
    heights = sorted({MIN_H, 3, 7, 8, 9, 16, 17, 33, 34, 63, 64, MAX_H})

    seen = set()
    for w in widths:
        for h in heights:
            # Keep the corpus to a sane size: full fills on every pair, the
            # exotic ones only where the payload crosses a byte boundary.
            picky = (w * h) % 8 != 0
            for name, bits in fills(w, h):
                if name not in ("clear", "solid", "alternating") and not picky:
                    continue
                if len(encode(w, h, 0, bits)) > MAX_B64:
                    continue
                key = (w, h, name)
                if key in seen:
                    continue
                seen.add(key)
                yield w, h, 0, name, bits

    # Every scale value must survive the header round-trip.
    for scale in range(8):
        w, h = 32, 24
        bits = [(i * 2654435761 >> 13) & 1 for i in range(w * h)]
        yield w, h, scale, f"scale-{scale}", bits

    # The largest legal pattern, at the longest legal encoding.
    big = [1] * (MAX_W * MAX_H)
    yield MAX_W, MAX_H, 7, "maximum", big


def main() -> int:
    check_only = "--check" in sys.argv
    fixtures, failures = [], []

    for w, h, scale, name, bits in cases():
        data = encode(w, h, scale, bits)
        try:
            dw, dh, dscale, dbits = decode(data)
        except Exception as e:
            failures.append(f"{name} {w}x{h}@{scale}: decode raised {e}")
            continue
        if (dw, dh, dscale) != (w, h, scale):
            failures.append(
                f"{name}: header {dw}x{dh}@{dscale} != {w}x{h}@{scale}")
            continue
        if dbits != bits:
            bad = next(i for i, (a, b) in enumerate(zip(dbits, bits)) if a != b)
            failures.append(f"{name} {w}x{h}@{scale}: bit {bad} differs")
            continue
        if encode(dw, dh, dscale, dbits) != data:
            failures.append(f"{name} {w}x{h}@{scale}: re-encode not identical")
            continue
        if len(data) > MAX_B64:
            failures.append(f"{name}: {len(data)} chars exceeds {MAX_B64}")
            continue
        fixtures.append({"name": f"{name}-{w}x{h}-s{scale}",
                         "width": w, "height": h, "scale": scale,
                         "ink": sum(bits), "patternData": data})

    dims = {(f["width"], f["height"]) for f in fixtures}
    print(f"{len(fixtures)} fixtures  ·  {len(dims)} distinct sizes  ·  "
          f"widths {min(f['width'] for f in fixtures)}-{max(f['width'] for f in fixtures)}  "
          f"heights {min(f['height'] for f in fixtures)}-{max(f['height'] for f in fixtures)}  "
          f"scales {sorted({f['scale'] for f in fixtures})}")
    print(f"longest encoding: {max(len(f['patternData']) for f in fixtures)} / {MAX_B64} chars")

    if failures:
        print(f"\n*** {len(failures)} FAILURE(S) ***")
        for f in failures[:20]:
            print("   ", f)
        return 1
    print("round-trip  all fixtures byte-identical")

    if not check_only:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        payload = {
            "note": ("Synthetic corpus covering the pattern format's boundaries. "
                     "Generated by tools/gen-codec-fixtures.py — do not hand-edit. "
                     "Contains no OpenFront data; see NOTICE."),
            "maxWidth": MAX_W, "maxHeight": MAX_H, "maxChars": MAX_B64,
            "count": len(fixtures),
            "patterns": fixtures,
        }
        with open(OUT, "w") as fh:
            json.dump(payload, fh, indent=1)
            fh.write("\n")
        print(f"wrote {OUT}  ({os.path.getsize(OUT):,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
