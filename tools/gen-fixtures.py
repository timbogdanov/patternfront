#!/usr/bin/env python3
"""
Generate the shared codec test fixtures from OpenFront's cosmetics.json.

docs/08-roadmap.md Phase 1 requires one fixture file consumed by BOTH the
TypeScript and PHP test suites, so the two codecs are provably tested against
identical data. Generating it (rather than committing OpenFront's file) also keeps
us clear of vendoring AGPL source — see docs/01-pattern-format.md §7.

Emits tests/fixtures/patterns.json:

    {
      "_meta":     { generator, source, count, format },
      "limits":    { maxWidth, maxHeight, maxBase64, ... },
      "patterns":  [ { name, patternData, width, height, scale, byteLength,
                       inkCoverage, bits } ],
      "roundTrip": [ ... same patternData, for encode(decode(x)) == x ]
    }

`bits` is a run-length encoding of the pixel buffer, so a test can verify decoded
*content*, not just that dimensions parse.

Run:  python3 tools/gen-fixtures.py [path/to/OpenFrontIO]
"""

from __future__ import annotations

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OPENFRONT = os.path.expanduser("~/Desktop/OpenFrontIO")
OUT = os.path.join(ROOT, "tests", "fixtures", "patterns.json")

MAX_W, MAX_H, MAX_B64 = 129, 65, 1403


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decode(b64: str):
    by = b64url_decode(b64)
    if len(by) < 3:
        raise ValueError("TruncatedHeader")
    if by[0] != 0:
        raise ValueError(f"UnsupportedVersion {by[0]}")
    b1, b2 = by[1], by[2]
    scale = b1 & 0x07
    width = (((b2 & 0x03) << 5) | ((b1 >> 3) & 0x1F)) + 2
    height = ((b2 >> 2) & 0x3F) + 2
    need = (width * height + 7) >> 3
    if len(by) - 3 < need:
        raise ValueError("TruncatedPayload")
    bits = [(by[3 + (i >> 3)] >> (i & 7)) & 1 for i in range(width * height)]
    return width, height, scale, by, bits


def encode(width: int, height: int, scale: int, bits: list[int]) -> str:
    w, h = width - 2, height - 2
    b1 = (scale & 0x07) | ((w & 0x1F) << 3)
    b2 = ((w >> 5) & 0x03) | ((h & 0x3F) << 2)
    payload = bytearray((width * height + 7) >> 3)
    for i, v in enumerate(bits):
        if v:
            payload[i >> 3] |= 1 << (i & 7)
    return base64.urlsafe_b64encode(
        bytes([0, b1, b2]) + bytes(payload)).decode().rstrip("=")


def rle(bits: list[int]) -> list[int]:
    """[value, runLength, value, runLength, ...] — compact and easy to expand
    in any language, which matters because both test suites read this."""
    if not bits:
        return []
    out, cur, n = [], bits[0], 0
    for b in bits:
        if b == cur:
            n += 1
        else:
            out += [cur, n]
            cur, n = b, 1
    return out + [cur, n]


def main() -> int:
    openfront = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OPENFRONT
    src = os.path.join(openfront, "resources/cosmetics/cosmetics.json")
    if not os.path.exists(src):
        print(f"cosmetics.json not found at {src}")
        print("Pass the OpenFrontIO checkout path as the first argument.")
        return 2

    raw = json.load(open(src, encoding="utf-8"))["patterns"]
    patterns, problems = [], []

    for b64, meta in sorted(raw.items(), key=lambda kv: kv[1].get("name", "")):
        name = meta.get("name", "?")
        try:
            w, h, scale, by, bits = decode(b64)
        except ValueError as exc:
            problems.append(f"{name}: {exc}")
            continue

        if encode(w, h, scale, bits) != b64:
            problems.append(f"{name}: round-trip mismatch")
        if not (2 <= w <= MAX_W and 2 <= h <= MAX_H):
            problems.append(f"{name}: dims {w}x{h} out of range")
        if len(b64) > MAX_B64:
            problems.append(f"{name}: {len(b64)} chars > {MAX_B64}")

        patterns.append({
            "name": name,
            "patternData": b64,
            "width": w,
            "height": h,
            "scale": scale,
            "byteLength": len(by),
            "inkCoverage": round(sum(bits) / len(bits), 6),
            "bits": rle(bits),
        })

    if problems:
        print("REFUSING TO WRITE — source data failed validation:")
        for p in problems:
            print(f"  {p}")
        return 1

    doc = {
        "_meta": {
            "generator": "tools/gen-fixtures.py",
            "source": "OpenFrontIO resources/cosmetics/cosmetics.json",
            "note": "Generated. Do not edit by hand — re-run the generator.",
            "count": len(patterns),
            "bitsEncoding": "run-length: [value, runLength, value, runLength, ...]",
            "bitSemantics": "0 = primary colour, 1 = secondary colour",
        },
        "limits": {
            "minWidth": 2, "maxWidth": MAX_W,
            "minHeight": 2, "maxHeight": MAX_H,
            "maxScale": 7, "maxBase64Chars": MAX_B64,
            "headerBytes": 3,
        },
        "patterns": patterns,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")

    size = os.path.getsize(OUT)
    print(f"wrote {os.path.relpath(OUT, ROOT)}  —  {len(patterns)} patterns, "
          f"{size:,} bytes")
    print(f"  dimensions  {min(p['width'] for p in patterns)}–"
          f"{max(p['width'] for p in patterns)} × "
          f"{min(p['height'] for p in patterns)}–"
          f"{max(p['height'] for p in patterns)}")
    print(f"  scales      {sorted({p['scale'] for p in patterns})}")
    print(f"  round-trip  {len(patterns)}/{len(patterns)} exact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
