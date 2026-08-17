#!/usr/bin/env python3
"""
Verify every factual claim the docs make about the OpenFront pattern format,
by decoding the real data in OpenFrontIO's cosmetics.json.

`docs/01-pattern-format.md` says: "If OpenFront changes upstream, re-run the
fixture test before trusting this document." This is that test.

Usage:
    python3 tools/verify-docs.py [path/to/OpenFrontIO]

Exit code 0 = all claims hold. Non-zero = a doc is now wrong.
"""

import base64
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs")
DEFAULT_OPENFRONT = os.path.expanduser("~/Desktop/OpenFrontIO")

_failures = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        _failures.append(label)


# --- codec (mirrors docs/01-pattern-format.md §1 and §5) --------------------

def b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decode_header(b64):
    by = b64url_decode(b64)
    if len(by) < 3:
        raise ValueError("TruncatedHeader")
    if by[0] != 0:
        raise ValueError("UnsupportedVersion")
    b1, b2 = by[1], by[2]
    scale = b1 & 0x07
    width = (((b2 & 0x03) << 5) | ((b1 >> 3) & 0x1F)) + 2
    height = ((b2 >> 2) & 0x3F) + 2
    if len(by) - 3 < (width * height + 7) >> 3:
        raise ValueError("TruncatedPayload")
    return width, height, scale, by


def encode(width, height, scale, bits):
    w, h = width - 2, height - 2
    b1 = (scale & 0x07) | ((w & 0x1F) << 3)
    b2 = ((w >> 5) & 0x03) | ((h & 0x3F) << 2)
    payload = bytearray((width * height + 7) >> 3)
    for i, v in enumerate(bits):
        if v:
            payload[i >> 3] |= 1 << (i & 7)
    raw = bytes([0, b1, b2]) + bytes(payload)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main():
    openfront = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OPENFRONT
    cosmetics = os.path.join(openfront, "resources/cosmetics/cosmetics.json")
    if not os.path.exists(cosmetics):
        print(f"cosmetics.json not found at {cosmetics}")
        print("Pass the OpenFrontIO checkout path as the first argument.")
        return 2

    patterns = json.load(open(cosmetics))["patterns"]

    print("=== Format boundary claims (doc 01 §2) ===")
    bits = 129 * 65
    total = 3 + ((bits + 7) >> 3)
    check("129x65 encodes to exactly 1403 base64url chars",
          math.ceil(total * 4 / 3) == 1403)
    check("width range is 2..129", (2, 129) == (0 + 2, 127 + 2))
    check("height range is 2..65", (2, 65) == (0 + 2, 63 + 2))

    print("\n=== Round-trip over every real pattern (doc 01 §6) ===")
    failed = []
    for b64, meta in patterns.items():
        try:
            w, h, sc, by = decode_header(b64)
        except ValueError as e:
            failed.append((meta.get("name"), str(e)))
            continue
        bits_list = [(by[3 + (i >> 3)] >> (i & 7)) & 1 for i in range(w * h)]
        if encode(w, h, sc, bits_list) != b64:
            failed.append((meta.get("name"), "roundtrip mismatch"))
    check(f"all {len(patterns)} patterns round-trip byte-identically",
          not failed, str(failed[:3]))
    check("doc 01 claims 31 fixtures", len(patterns) == 31,
          f"actual {len(patterns)}")

    print("\n=== Known-value example (doc 01 §3) ===")
    w, h, sc, by = decode_header("ABMIVVU")
    check("ABMIVVU is 4x4 scale 3", (w, h, sc) == (4, 4, 3), f"got {w}x{h} s{sc}")
    check("ABMIVVU is named stripes_v",
          patterns.get("ABMIVVU", {}).get("name") == "stripes_v")
    check("ABMIVVU alternates columns (bit0=primary)",
          [(by[3] >> i) & 1 for i in range(4)] == [1, 0, 1, 0])

    print("\n=== Fixture table in doc 01 matches reality ===")
    doc = open(os.path.join(DOCS, "01-pattern-format.md")).read()
    rows = re.findall(
        r"^\| *\d+ \| `([^`]+)` \| `([^`]+)` \| (\d+)×(\d+) \| (\d+) \| (\d+) \|",
        doc, re.M)
    check("31 rows present in the doc table", len(rows) == 31, f"got {len(rows)}")
    real_names = {m.get("name") for m in patterns.values()}
    check("doc names match cosmetics.json exactly",
          {r[0] for r in rows} == real_names)

    mismatched = []
    by_name = {m.get("name"): k for k, m in patterns.items()}
    for name, _data, dw, dh, dsc, dbytes in rows:
        w, h, sc, by = decode_header(by_name[name])
        if (w, h, sc, len(by)) != (int(dw), int(dh), int(dsc), int(dbytes)):
            mismatched.append(name)
    check("every row's W/H/scale/bytes match a real decode",
          not mismatched, str(mismatched[:3]))

    print("\n=== Observed-maxima claims (doc 01 §6.1) ===")
    dims = [decode_header(k)[:3] for k in patterns]
    check("max observed width is 66", max(d[0] for d in dims) == 66)
    check("max observed height is 35", max(d[1] for d in dims) == 35)
    check("scales 0..3 are used", {d[2] for d in dims} == {0, 1, 2, 3})
    check("16x8 appears 6 times",
          sum(1 for d in dims if d[:2] == (16, 8)) == 6)
    check("16x16 appears 5 times",
          sum(1 for d in dims if d[:2] == (16, 16)) == 5)
    check("no real pattern exceeds the format limits",
          all(2 <= d[0] <= 129 and 2 <= d[1] <= 65 for d in dims))

    print("\n=== Cost model arithmetic (doc 07 §3, §4) ===")
    packs = [(10, 220, 0.0428), (25, 600, 0.0400), (50, 1300, 0.0371)]
    for usd, credits, claimed in packs:
        per = (usd - (usd * 0.029 + 0.30)) / credits
        check(f"${usd} pack nets ${claimed}/credit",
              abs(per - claimed) < 0.00005, f"computed {per:.4f}")

    worst = min((usd - (usd * 0.029 + 0.30)) / cr for usd, cr, _ in packs)
    llm = 0.0005
    actions = [("geometric", 1, llm),
               ("art x1", 1, 0.030 + llm),
               ("art x4", 4, 4 * 0.030 + llm),
               ("edit", 6, 0.180)]
    for name, credits, cost in actions:
        margin = credits * worst - cost
        check(f"{name} is profitable at the worst tier",
              margin > 0, f"margin ${margin:.4f}")

    print("\n=== Placeholder scan ===")
    stale = re.compile(r"\b(TBD|TODO|FIXME|XXX)\b")
    hits = [f for f in sorted(os.listdir(DOCS))
            if f.endswith(".md") and stale.search(open(os.path.join(DOCS, f)).read())]
    check("no placeholders in any doc", not hits, str(hits))

    print()
    if _failures:
        print(f"*** {len(_failures)} CHECK(S) FAILED ***")
        for f in _failures:
            print(f"    - {f}")
        return 1
    print("ALL CHECKS PASSED — the docs match the source data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
