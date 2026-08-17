#!/usr/bin/env python3
"""
Check the stamp library in app/patternfront.html.

A stamp IS a small 1-bit OpenFront pattern — it reuses the codec that's already
verified byte-exact against all 31 real game patterns, so there is no second
format to trust. This asserts that claim rather than assuming it:

    every stamp decodes · fits 129x65 · re-encodes byte-identically
    names are unique · payloads are unique

Ink coverage (8%-75%) is an ICON LEGIBILITY rule and applies to the AUTHORED
stamps only. The `game` group is imported from OpenFront's cosmetics.json and
contains tiling patterns — `sparse_dots` is 2% ink by design. Rejecting those
would mean rejecting data the game itself ships.

Run:  python3 tools/verify-stamps.py
"""

from __future__ import annotations

import base64
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "patternfront.html")

MAX_W, MAX_H, MAX_B64 = 129, 65, 1403
INK_LO, INK_HI = 0.08, 0.75
IMPORTED = {"game"}          # OpenFront's own patterns — tiling, not icons


def decode(s: str):
    b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    if len(b) < 3:
        raise ValueError("too short")
    if b[0] != 0:
        raise ValueError(f"unsupported version {b[0]}")
    scale = b[1] & 7
    w = (((b[2] & 3) << 5) | ((b[1] >> 3) & 31)) + 2
    h = ((b[2] >> 2) & 63) + 2
    if len(b) - 3 < (w * h + 7) // 8:
        raise ValueError("payload truncated")
    bits = [(b[3 + (i >> 3)] >> (i & 7)) & 1 for i in range(w * h)]
    return w, h, scale, bits


def encode(w: int, h: int, scale: int, bits) -> str:
    raw = bytearray(3 + ((w * h + 7) // 8))
    raw[1] = (scale & 7) | (((w - 2) & 31) << 3)
    raw[2] = (((w - 2) >> 5) & 3) | (((h - 2) & 63) << 2)
    for i, v in enumerate(bits):
        if v:
            raw[3 + (i >> 3)] |= 1 << (i & 7)
    return base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


def main() -> int:
    src = open(APP).read()
    js = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))
    stamps = re.findall(r"\['([a-z]+)','([a-z0-9_-]+)','([A-Za-z0-9_-]+)'\]", js)
    if not stamps:
        print("no STAMPS table found")
        return 2

    bad: list[str] = []
    authored = 0
    for group, name, data in stamps:
        try:
            w, h, scale, bits = decode(data)
        except Exception as e:
            bad.append(f"{group}/{name}: {e}")
            continue
        if w > MAX_W or h > MAX_H:
            bad.append(f"{group}/{name}: {w}x{h} exceeds {MAX_W}x{MAX_H}")
            continue
        if len(data) > MAX_B64:
            bad.append(f"{group}/{name}: {len(data)} chars, max {MAX_B64}")
            continue
        if encode(w, h, scale, bits) != data:
            bad.append(f"{group}/{name}: re-encode is not byte-identical")
            continue
        if group in IMPORTED:
            continue
        authored += 1
        ink = sum(bits) / (w * h)
        if not (INK_LO <= ink <= INK_HI):
            bad.append(f"{group}/{name}: {ink:.0%} ink, outside {INK_LO:.0%}-{INK_HI:.0%}")

    names = [n for _, n, _ in stamps]
    dupe_n = sorted({n for n in names if names.count(n) > 1})
    datas = [d for _, _, d in stamps]
    dupe_d = sorted({d for d in datas if datas.count(d) > 1})

    print(f"{len(stamps)} stamps  ({authored} authored, "
          f"{len(stamps) - authored} imported from OpenFront)")
    ok = True
    for label, cond, detail in (
        ("all decode, fit 129x65, re-encode byte-identically", not bad, "\n    ".join(bad)),
        ("names are unique", not dupe_n, str(dupe_n)),
        ("no two stamps are the same artwork", not dupe_d, f"{len(dupe_d)} duplicate payload(s)"),
    ):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"\n    {detail}" if not cond else ""))
        ok = ok and cond

    print("ALL STAMP CHECKS PASSED" if ok else "*** STAMP CHECKS FAILED ***")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
