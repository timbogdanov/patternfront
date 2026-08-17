#!/usr/bin/env python3
"""
Validate every example in resources/prompts/router.md against the real DSL renderer.

Few-shot examples are the strongest signal in the prompt. An example that does not
render, does not tile, or produces a degenerate pattern teaches the model to emit
exactly that mistake — so they must be executable, not merely plausible.

Checks each `parametric` example:
  * parses as JSON,
  * validates against the DSL schema,
  * renders,
  * tiles exactly (autoSize honoured),
  * fits the OpenFront format limits,
  * lands in a sane ink-coverage band.

Checks each `diffusion` example carries a refined_prompt free of medium words.

Run:  python3 tools/verify-prompt.py
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from dsl_prototype import (  # noqa: E402
    MAX_B64, MAX_H, MAX_W, MIN_H, MIN_W,
    encode, render, tiles_exactly,
)

PROMPT = os.path.join(ROOT, "resources", "prompts", "router.md")

# Words the refined_prompt must not contain — they describe the medium, which the
# pixel-art model already encodes, and including them degrades output.
MEDIUM_WORDS = {"pixel", "pixelart", "8-bit", "8bit", "16-bit", "sprite",
                "retro", "pixelated", "low-res", "lowres"}

failures = []


def check(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def extract_json_blocks(text: str) -> tuple[list[dict], int]:
    """Return (parsed examples, skipped template count).

    The two blocks under "Output format" are shape templates carrying `...` and
    `<placeholder>` markers. They are documentation, not examples, and are not
    expected to parse.
    """
    blocks, templates = [], 0
    for m in re.finditer(r"```json\n(.*?)\n```", text, re.S):
        raw = m.group(1).strip()
        if "..." in raw or re.search(r"<[a-z ]+>", raw):
            templates += 1
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            failures.append(f"unparseable JSON block: {exc}")
            print(f"  [FAIL] JSON parse error: {exc}\n{raw[:200]}")
    return blocks, templates


def main() -> int:
    if not os.path.exists(PROMPT):
        print(f"missing {PROMPT}")
        return 2
    text = open(PROMPT).read()
    blocks, templates = extract_json_blocks(text)

    # The two format-template blocks at the top use "..." placeholders and are
    # documentation, not examples. Real examples always carry a rationale AND
    # either a concrete shape or a refined_prompt.
    examples = [
        b for b in blocks
        if b.get("engine") == "diffusion"
        or (b.get("engine") == "parametric"
            and b.get("program", {}).get("layers")
            and all(isinstance(l.get("shape"), dict) and "type" in l["shape"]
                    for l in b["program"]["layers"]))
    ]

    print(f"=== {len(blocks)} examples + {templates} format templates (skipped) ===\n")

    para = [e for e in examples if e["engine"] == "parametric"]
    diff = [e for e in examples if e["engine"] == "diffusion"]

    print(f"=== {len(para)} parametric examples ===")
    for i, ex in enumerate(para, 1):
        name = ex.get("rationale", "")[:38]
        try:
            w, h, scale, buf = render(ex["program"])
        except Exception as exc:                                    # noqa: BLE001
            check(f"{i}. {name}", False, f"render error: {exc}")
            continue

        b64 = encode(w, h, scale, buf)
        exact, px, py = tiles_exactly(ex["program"], w, h)
        ink = 100.0 * sum(buf) / len(buf)
        auto = ex["program"]["canvas"].get("autoSize", True)

        problems = []
        if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
            problems.append(f"dims {w}x{h} out of range")
        if len(b64) > MAX_B64:
            problems.append(f"b64 {len(b64)} > {MAX_B64}")
        if auto and not exact:
            problems.append(f"{w}x{h} not a multiple of period {px}x{py}")
        # `solid` is uniform by definition; every other shape being near-uniform
        # is the silent failure mode doc 03 §8 warns about.
        is_solid = all(l["shape"]["type"] == "solid"
                       for l in ex["program"]["layers"])
        if not is_solid and not (5.0 <= ink <= 95.0):
            problems.append(f"ink {ink:.1f}% degenerate")

        check(f"{i}. {name}", not problems,
              f"{w}×{h} s{scale} ink {ink:.0f}% period {px}×{py} "
              f"{len(b64)}ch — {'; '.join(problems) if problems else 'ok'}")

    print(f"\n=== {len(diff)} diffusion examples ===")
    for i, ex in enumerate(diff, 1):
        rp = ex.get("refined_prompt", "")
        bad = sorted(w for w in MEDIUM_WORDS
                     if re.search(rf"\b{re.escape(w)}\b", rp, re.I))
        check(f"{i}. refined_prompt has no medium words", not bad,
              f"{rp!r}" + (f" — contains {bad}" if bad else ""))

    print("\n=== coverage: every shape type appears somewhere in the prompt ===")
    from dsl_prototype import SHAPES
    body = text
    missing = [t for t in SHAPES if f"`{t}`" not in body]
    check("all 15 shape types documented", not missing, str(missing))

    used = {l["shape"]["type"] for e in para for l in e["program"]["layers"]}
    print(f"  shape types demonstrated in examples: {len(used)}/{len(SHAPES)} "
          f"({', '.join(sorted(used))})")

    print()
    if failures:
        print(f"*** {len(failures)} FAILURE(S) ***")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("ALL ROUTER PROMPT EXAMPLES VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
