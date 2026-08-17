# 03 — AI Integration

> This is the document that decides whether the product is good. Everything else is a competent pixel
> editor; this is the part that has to earn its place.

---

## 1. The thesis

Two research findings shape this design, and they point the same direction.

**Finding 1 — LLMs draw pixels badly.** The SwordsBench evaluation of tool-calling LLMs drawing sprites
through an Aseprite MCP server scored the best model, Claude Opus 4, at **2.5 out of 6**. Models placed
pixels, but form and consistency broke down. Directly asking a language model to emit a bitmap is a
losing approach.

**Finding 2 — diffusion models break the grid.** General image models produce output that reads as pixel
art at thumbnail size and falls apart on inspection: off-grid edges, hundreds of near-identical colours,
soft anti-aliased boundaries. Only models trained specifically on pixel art hold the grid.

Now add a domain observation. Look at what real OpenFront patterns actually *are*
(`01-pattern-format.md` §6): `stripes_v`, `stripes_h`, `checkerboard`, `vertical_bars`,
`horizontal_stripes`, `diagonal`, `diagonal_stripe`, `mini_cross`, `cross`, `circuit_board`,
`scattered_dots`, `sparse_dots`. **Roughly two-thirds of the shipped set is geometric and periodic.**
The pictorial ones (`goat`, `grogu`, `t_rex`, `white_rabbit`) are a minority.

So: the single most common request — "give me diagonal stripes" — is a request diffusion is *bad* at
and arithmetic is *perfect* at. A diffusion model asked for diagonal stripes will produce stripes that
are approximately parallel, approximately evenly spaced, and that do not tile. A four-line function
produces stripes that are exactly parallel, exactly spaced, and tile by construction.

**The conclusion: this is not one model behind a prompt box. It is a router over four engines, and the
cheapest engine handles the most common request.**

## 2. The four engines

| | Engine | Handles | Backend | Latency | Cost |
|---|---|---|---|---|---|
| **A** | **Parametric** | geometric, periodic, textural | LLM → JSON DSL → deterministic renderer | ~1 s | ~$0.0005 |
| **B** | **Diffusion** | pictorial subjects | Retro Diffusion `rd_fast__1_bit` | 3–8 s | ~$0.03/img |
| **C** | **Conversion** | user-supplied images | client-side pipeline (`04`) | <100 ms | **$0** |
| **D** | **Edit** | localised changes to existing work | Retro Diffusion `rd_pro__edit` | 5–10 s | ~$0.18 |

Engine A is the differentiator. It is ~60× cheaper than B, ~5× faster, and produces *strictly better*
results on the prompts it handles — not "good enough for the price", genuinely better, because the
output is exact rather than approximate and tiles perfectly by construction.

Engine C is free and runs entirely in the browser (`04-image-to-pattern.md`).

## 3. The router

Routing and generation happen in **one LLM call**, not two. The model is asked to either emit a DSL
program or decline and hand off:

```
POST → LLM with the pattern DSL schema in the system prompt
       user prompt + current canvas dimensions

← one of:
   { "engine": "parametric", "program": { … }, "rationale": "…" }
   { "engine": "diffusion",  "refined_prompt": "…", "invert": false, "rationale": "…" }
```

The model decides. The system prompt instructs it to prefer `parametric` whenever the request can be
expressed periodically, and to fall back to `diffusion` only for recognisable subjects — a creature, an
object, a logo, a face.

Escape hatches, because the router will sometimes be wrong:

- The UI shows which engine ran and offers **"try the other one"** as a one-click retry.
- A user can force an engine from a segmented control before generating.
- If DSL validation fails (§4.4), the request falls through to diffusion automatically rather than
  erroring.

### 3.1 Worked routing examples

| Prompt | Engine | Why |
|---|---|---|
| "diagonal stripes with a thin gap" | A | Periodic, exactly expressible |
| "checkerboard but the squares are 3 wide and 5 tall" | A | Parametric with unequal cell dims |
| "chain link fence" | A | `diagonal` × `diagonal` intersection |
| "scattered dots, sparse" | A | `dots` with jitter + low density |
| "brick wall" | A | `brick` primitive |
| "waves" | A | `wave` primitive |
| "the letters KDR" | A | `text` primitive with the built-in 5×7 font |
| "a wolf head" | B | Recognisable subject, not periodic |
| "flames" | B | Organic, no clean periodicity |
| "a skull, repeating" | B → then tile-repair | Pictorial motif, tiled by the renderer |

## 4. Engine A — the parametric DSL

> **A working reference implementation exists: `tools/dsl_prototype.py`.**
> All 15 primitives, the composition ops, validation, LCM sizing, and the seam scorer are implemented
> and tested. `python3 tools/dsl_demo.py` renders 28 example programs and asserts every claim this
> section makes — currently **28/28 tile exactly**, all within the format limits, largest output 220 of
> 1403 permitted characters. Visual output: `docs/assets/dsl-gallery.png`.
>
> The TypeScript and PHP implementations should be **ported from that file**, not written from this
> prose. Building it corrected three errors in this document (§4.3 `diagonal` period, §4.3 `text`
> leading, and the whole of §6) — treat the code as authoritative where they disagree.

### 4.1 Why a DSL rather than "LLM writes code"

Letting a model emit executable code to draw the pattern would be more expressive and considerably worse:
it is an arbitrary-code-execution surface, it is non-deterministic to validate, and it removes the
tiling guarantee. A closed DSL with clamped numeric ranges can be validated completely, cannot fail in
interesting ways, and — critically — **lets the renderer guarantee that output tiles**.

### 4.2 Schema

```jsonc
{
  "canvas": { "width": 16, "height": 16, "scale": 1, "autoSize": true },
  "layers": [
    { "op": "set",       "shape": { … } },   // first layer establishes the base
    { "op": "union",     "shape": { … } },
    { "op": "intersect", "shape": { … } },
    { "op": "xor",       "shape": { … } },
    { "op": "subtract",  "shape": { … } }
  ],
  "post": { "invert": false, "mirrorX": false, "mirrorY": false, "rotate90": 0 }
}
```

Layers compose left to right over a bit buffer. `op` on the first layer is always treated as `set`.

### 4.3 Shape primitives

Every primitive is **periodic by construction**. Each declares its period in x and y; the renderer uses
those to guarantee tiling (§4.5).

| `type` | Parameters | Period |
|---|---|---|
| `solid` | — | 1 × 1 |
| `stripes` | `axis: "h"\|"v"`, `period` 2–64, `thickness` 1–63, `phase` 0–63 | `period` on `axis` |
| `diagonal` | `dx` 1–8, `dy` 1–8, `period` 2–64, `thickness` 1–63, `phase` 0–63 | `period/gcd(dy,period)` × `period/gcd(dx,period)` |
| `checker` | `cellW` 1–32, `cellH` 1–32, `phase` 0–1 | `2·cellW` × `2·cellH` |
| `grid` | `periodX` 2–64, `periodY` 2–64, `lineX` 1–8, `lineY` 1–8, `phaseX`, `phaseY` | `periodX` × `periodY` |
| `dots` | `periodX` 2–64, `periodY` 2–64, `radius` 0–16, `shape: "square"\|"circle"\|"diamond"`, `rowOffset` 0–63, `jitter` 0–4, `seed` | `periodX` × `periodY` (×2 if `rowOffset`) |
| `brick` | `brickW` 2–64, `brickH` 1–32, `mortar` 1–4, `offset` 0–63 | `brickW` × `2·brickH` |
| `wave` | `axis`, `period` 2–64, `amplitude` 1–16, `thickness` 1–8, `phase` | `period` × `2·amplitude` |
| `zigzag` | `axis`, `period` 2–64, `amplitude` 1–16, `thickness` 1–8 | `period` × `2·amplitude` |
| `triangles` | `size` 2–32, `orientation` | `2·size` × `size` |
| `rings` | `period` 2–32, `thickness` 1–8, `cx`, `cy` | `period` × `period` |
| `halftone` | `period` 2–32, `level` 0–1, `angle: 0\|45` | `period` × `period` |
| `noise` | `density` 0–1, `seed`, `blue` bool | tile-locked to canvas |
| `text` | `glyphs` (≤8 chars, `[A-Z0-9]`), `font: "5x7"\|"3x5"`, `tracking` 0–3, `leading` 0–8 (default **2**) | `len·(gw+tracking)` × `gh+leading` |
| `border` | `inset` 0–16, `thickness` 1–8 | canvas |

`noise` and `text` are canvas-locked rather than freely periodic; the renderer handles their tiling by
generating within the final canvas bounds and wrapping.

### 4.4 Validation — the injection boundary

The LLM's output is untrusted. Before anything renders:

1. Parse as strict JSON. Reject on any parse error.
2. Validate against the schema. **Unknown keys are a rejection**, not a warning.
3. Clamp every numeric to its declared range. Out-of-range is clamped, not rejected — a model that says
   `period: 500` meant "big", and clamping to 64 serves the user better than an error.
4. Reject `thickness > period` (degenerate: produces solid fill); clamp to `period - 1`.
5. Cap `layers` at **8**.
6. `text.glyphs` is filtered to `[A-Z0-9]` and truncated to 8.
7. `seed` is coerced to a 32-bit integer.

After this, the program is *provably* incapable of doing anything except producing a bitmap within
canvas bounds. There is no path from prompt text to code execution, file access, or unbounded
computation. That property is why the DSL exists.

If validation rejects outright (steps 1, 2, 5), fall through to Engine B rather than surfacing an error.

### 4.5 The tiling guarantee

This is the mathematical core, and the reason Engine A beats diffusion on its home turf.

Every primitive has a period `(px, py)`. For a program's layers, compute:

```
Px = lcm(px₁, px₂, …)      Py = lcm(py₁, py₂, …)
```

If `canvas.autoSize` is true, set the canvas to the smallest multiple of `(Px, Py)` that fits within
129×65 and is at least 8×8. The pattern then tiles **exactly** — its seam score (§6) is zero by
construction, not by luck.

If the user has pinned dimensions, and `Px` does not divide `width`, the renderer:

1. tries to nudge each primitive's `period` by ±1 to find a divisor of `width` — usually succeeds and is
   visually indistinguishable;
2. failing that, renders anyway and reports a non-zero seam score with a "snap to tiling size" button.

The nudge step is what makes "diagonal stripes" on a user's arbitrary 23×17 canvas still look right. It
is worth implementing properly.

### 4.6 Example — "diagonal stripes with a thin gap"

```json
{
  "canvas": { "width": 16, "height": 16, "scale": 1, "autoSize": true },
  "layers": [
    { "op": "set", "shape": {
        "type": "diagonal", "dx": 1, "dy": 1,
        "period": 8, "thickness": 5, "phase": 0 } }
  ],
  "post": { "invert": false, "mirrorX": false, "mirrorY": false, "rotate90": 0 }
}
```

`period 8, thickness 5` → 5 on, 3 off. `lcm(8,8) = 8`, canvas 16×16 is a multiple → tiles exactly.
Renders in under a millisecond. Costs a twentieth of a cent. Cannot seam.

### 4.7 Example — "chain link fence"

```json
{
  "canvas": { "width": 16, "height": 16, "scale": 1, "autoSize": true },
  "layers": [
    { "op": "set",   "shape": { "type": "diagonal", "dx": 1, "dy":  1,
                                "period": 8, "thickness": 2, "phase": 0 } },
    { "op": "union", "shape": { "type": "diagonal", "dx": 1, "dy": -1,
                                "period": 8, "thickness": 2, "phase": 0 } }
  ],
  "post": { "invert": false, "mirrorX": false, "mirrorY": false, "rotate90": 0 }
}
```

### 4.8 System prompt

**Written: `resources/prompts/router.md`.** Contents:

- Role: convert pattern requests into DSL programs for a **1-bit tiling** canvas.
- The routing decision, stated first, with the tie-break rule (when torn, choose `parametric`).
- The complete schema and primitive table, plus the parameter gotchas that actually bite —
  `thickness < period`, small `radius`, `leading ≥ 2`, and the 20–70% ink target.
- Guidance on `scale`, which is the least intuitive field and the one most likely to be set wrongly.
- Rules for rewriting a user prompt into `refined_prompt` for diffusion (strip medium words, add
  silhouette cues).
- **18 few-shot examples: 16 parametric covering all 15 shapes, plus 2 diffusion.**
- Output contract: a single JSON object, nothing else.

Use structured output / JSON mode if the provider supports it. It removes a whole class of parse failure.

**The examples are executable and tested.** `tools/verify-prompt.py` extracts every JSON block from the
prompt, renders each parametric program through the real DSL, and asserts it tiles exactly, fits the
format limits, and is not degenerate; it also checks each `refined_prompt` for leaked medium words and
verifies all 15 shapes are demonstrated. Currently **18/18 valid, 15/15 shape coverage**.

This matters more than it might look: few-shot examples are the strongest signal in the prompt, so an
example that does not actually render teaches the model to reproduce exactly that mistake. Run this
check in CI alongside the codec tests.

## 5. Engines B and D — Retro Diffusion

### 5.1 Why this provider

Evaluated against general image models and other pixel-art services. It wins on three specifics that
matter here:

1. **`rd_fast__1_bit` is a native two-colour style.** Output is already monochrome. Every alternative
   requires generating full colour and then reducing, which loses control over exactly the decision that
   defines a 1-bit pattern: what becomes primary and what becomes secondary.
2. **`tile_x` / `tile_y` produce seamless output.** OpenFront patterns tile by modulo
   (`01-pattern-format.md` §4). A provider without seamless generation is generating the wrong thing.
3. **Cost.** `rd_fast__1_bit` is roughly $0.03 per image, cheap enough that returning four variants is
   the default rather than a premium.

### 5.2 Contract

```
POST https://api.retrodiffusion.ai/v1/inferences
X-RD-Token: <key>            # keys are prefixed rdpk-
Content-Type: application/json
```

Generation (Engine B):

```jsonc
{
  "prompt": "<refined_prompt from the router — never say 'pixel art'>",
  "prompt_style": "rd_fast__1_bit",
  "width": 128, "height": 128,      // 64–384 for this style; see §5.3
  "num_images": 4,                  // ≤16 for rd_fast
  "tile_x": true, "tile_y": true,
  "seed": 1234567
}
```

Region edit (Engine D):

```jsonc
{
  "prompt": "<user's description of the change>",
  "prompt_style": "rd_pro__edit",
  "width": 128, "height": 128,
  "num_images": 1,                  // ≤4 for RD Pro
  "input_image": "<base64 PNG, no data: prefix>",
  "strength": 0.6
}
```

Response: `{ base64_images: string[], balance_cost, remaining_balance, created_at, model }`.

`balance_cost` is the authoritative figure — record it, don't estimate (`07-cost-and-abuse.md` §4).

### 5.3 The resolution mismatch, and how it's handled

`rd_fast__1_bit` generates at **64–384 px**. OpenFront patterns are at most **129×65**, and typically
16×8 to 32×32. These do not line up, and how we bridge them determines output quality.

Do **not** ask the model for 32×32 directly. At that size the style produces mush — there are not enough
pixels for the model to establish form.

Instead:

1. Generate at **128×128** (or 128×64 for a 2:1 target), where the style performs well.
2. Bring the result back to the browser as a PNG.
3. Run it through the **same client-side pipeline as Engine C** (`04-image-to-pattern.md`) to reach the
   user's actual canvas size, with the threshold and dither controls live.

This is a genuinely better design than server-side downscaling, for a non-obvious reason: **the user
gets to tune the reduction.** The model's idea of which regions are dark is not always the user's, and
at 16×8 that judgement is most of the result. Handing the user a threshold slider over a 128×128
intermediate gives far better outcomes than any fixed server-side reduction.

It also means Engines B and C share one code path, so the reduction quality improves for both at once.

### 5.4 Prompt hygiene

Per the provider's guidance, the prompt should describe the *subject*, not the medium — saying "pixel
art" degrades output because the style already encodes it. The router's `refined_prompt` field exists to
strip that: a user typing "pixel art wolf head" yields `refined_prompt: "wolf head, bold silhouette,
high contrast"`.

The router also appends silhouette-friendly guidance for 1-bit, since forms that rely on mid-tones
disappear entirely at two colours.

## 6. Tileability — a first-class concern

A pattern that looks good flat and seams badly in game is a broken pattern, and the user cannot see the
defect without a correct preview. So we measure it.

### 6.1 Two checks, not one

There are two situations and they need different tools. Conflating them was a real bug in an earlier
draft of this document — see §6.4.

**A. Output with a known generating function (Engine A).** Don't measure anything. Each primitive
declares its period, so the pattern tiles perfectly **iff** the canvas is a whole number of periods:

```
tiles_exactly  ⟺  width % lcm(period_x…) == 0  ∧  height % lcm(period_y…) == 0
```

This is exact, costs nothing, and is what §4.5 means by "seamless by construction". Assert the
construction; do not score the result.

**B. Output with no generating function** — hand-drawn, imported, or diffusion. Here we only have the
bitmap, and need a heuristic. Two independent failure modes have to be covered:

**b1 — Edge discontinuity.** Is the wrap join an *outlier* among the pattern's own joins?

```
colDiffs   = [ Σ_y [ px(x,y) ≠ px(x+1,y) ]  for x in 0..width-2 ]
wrapH      =   Σ_y [ px(width-1,y) ≠ px(0,y) ]
seamScoreH = wrapH / max(p90(colDiffs), 1)
```

Use the **90th percentile**, not the mean. This is the crux: inside a periodic pattern most adjacent
column pairs are identical, which drags the mean to near zero and makes every legitimate stripe boundary
look like a defect. Vertical stripes of period 8 on a 32-wide canvas tile perfectly and score **4.4**
under a mean-normalised metric, and **1.0** under the percentile one.

**b2 — Broken cadence.** A pattern can have a perfectly ordinary-looking wrap join and still tile badly,
because the *rhythm* is wrong. Period-7 stripes on a 32-wide canvas are the clean example: the edge
looks normal, but the stripe spacing breaks. Local adjacency cannot see this, so:

1. Recover the intrinsic period from the **leading 3/4** of the axis (excluding the edge region, so an
   edge defect cannot corrupt the measurement meant to catch it).
2. If that period fits with error < 2%, the pattern counts as periodic. Then either:
   - `span % period ≠ 0` → the cadence cannot survive tiling at all, **or**
   - the toroidal error at that period exceeds the interior error → periodic inside, broken across the
     wrap (this is what catches a duplicated or stray edge column).
3. Either condition sets the score to **3.0**.

Final score is `max(b1, b2)` per axis. Badge: **Seamless** ≤1.3 · **Slight seam** ≤2.0 ·
**Visible seam** >2.0.

### 6.2 Validation

`tools/dsl_demo.py` tests both directions, because a metric that never fires and a metric that always
fires are equally useless:

| Control | Expected | Result |
|---|---|---|
| stripes period 8, width 32 | Seamless | 1.00 ✓ |
| checker cell 4, width 32 | Seamless | 1.00 ✓ |
| white noise | Seamless | 0.70 ✓ |
| stripes period **7**, width 32 | flagged | 3.00 ✓ |
| duplicated final column | flagged | 3.00 ✓ |
| stray ink line at `x = w-1` | flagged | 3.00 ✓ |
| density gradient | flagged | 1.78 ✓ |

Three false-positive controls and four false-negative controls, all passing.

### 6.3 Repair

Offered, never applied automatically, because repair changes the user's art:

| Method | What it does | Best for |
|---|---|---|
| **Mirror wrap** | Mirror the pattern into a 2W×2H tile | Any pattern; doubles size, always seamless |
| **Edge blend** | Re-dither an N-pixel band at each wrap edge toward the opposing edge | Textural patterns |
| **Snap to period** | Crop/extend the canvas to the detected dominant period | Near-periodic patterns |
| **Offset test** | Roll the pattern by (W/2, H/2) so seams land centrally where they can be hand-fixed | Manual repair |

"Offset test" is the one experienced pixel artists reach for — it is the standard seamless-texture
workflow and Rin (`00-overview.md` §5) will expect it.

`Snap to period` should use the same interior-window period detection as §6.1 b2, not a naive
autocorrelation over the whole axis — otherwise the edge defect being repaired skews the period it
snaps to.

### 6.4 Why this section was rewritten

Worth recording, because the original mistake is an easy one to make again.

The first draft specified a single metric: wrap-edge difference count divided by the **mean** interior
difference count. Building `tools/dsl_prototype.py` and running it over all 28 gallery patterns showed
it flagged **17 of them** as seaming — including `stripes_v`, `checkerboard`, and `grid`, which tile
perfectly and demonstrably.

The cause: inside a periodic pattern, most adjacent column pairs are *identical*, so the mean interior
difference is near zero, and any legitimate boundary landing on the wrap scores as a large multiple of
it. The metric was measuring "is there a transition here", when the question is "is this transition
unusual for this pattern".

Two things came out of that:

- Swap the mean for a high percentile, which makes the comparison rank-based instead of magnitude-based.
- Stop scoring Engine A output at all. We know its period analytically; measuring a bitmap to rediscover
  a fact we already have is both slower and less reliable.

Had this shipped, the seam badge would have read "Visible seam" on nearly every geometric pattern the
product generates, and users would have learned to ignore it — which is worse than not having it.

Every failure mode, and what the user sees. Nothing here should ever produce a raw exception in the UI.

| Failure | Handling | Credits |
|---|---|---|
| LLM returns unparseable JSON | Retry once with a "JSON only" reminder, then fall through to Engine B | Not charged for the LLM attempt |
| DSL fails validation | Fall through to Engine B silently | — |
| Provider 4xx (bad request) | Do **not** retry. Log full request. Show "that prompt didn't work, try rephrasing" | **Refunded** |
| Provider 429 | Retry with backoff, max 2 | Charged only on success |
| Provider 5xx / timeout | Retry once, then fail | **Refunded** |
| Provider returns fewer images than requested | Accept, charge `balance_cost` as reported | Actual only |
| Job exceeds 120 s | Swept to `failed` by the scheduler | **Refunded** |
| `SpendGuard` ceiling hit | Rejected before dispatch, honest message | Not charged |
| Insufficient credits | Rejected before dispatch, top-up prompt | — |

Refunds are ledger entries, not balance mutations (`06-data-model.md` §5). Every refund is traceable to
the generation that caused it.

## 8. Quality evaluation

"AI has to work very well" needs a way to tell whether it does. Build this in Phase 4, before tuning
prompts, or tuning becomes guesswork.

**A fixed prompt set** of 40 prompts: 25 geometric, 15 pictorial, drawn from what the routing table and
real OpenFront pattern names suggest people want.

Automated metrics, run on every prompt-template change:

| Metric | Target |
|---|---|
| Routing accuracy vs. a hand-labelled expected engine | ≥ 90% |
| DSL validation pass rate (Engine A) | ≥ 95% |
| Seam score ≤ 1.3 | 100% for A, ≥ 70% for B with tiling flags |
| Ink coverage in 15–85% | ≥ 90% (all-black or all-white output is a failure) |
| Median latency, Engine A | ≤ 1.5 s |
| Cost per accepted result | tracked, no target |

The **ink coverage** check catches the most common silent failure: a threshold landing badly and
producing a nearly solid pattern that is technically valid and completely useless.

Human review on the same 40 prompts before each release: side-by-side at map scale, scored 1–5. Slow,
but the automated metrics cannot see "this is ugly".

## 9. What we are not doing

- **No LLM pixel-pushing.** No "here is a 16×16 grid, edit cell (4,7)". Finding 1 says it does not work,
  and the DSL covers the same ground deterministically.
- **No fine-tuning.** A LoRA on OpenFront patterns is plausible eventually. Thirty-one training examples
  is not a dataset.
- **No agentic multi-turn refinement loop.** "Generate, critique, regenerate" multiplies cost by 3–5×
  for a marginal gain over letting the user pick from four variants. The user is a better critic and is
  already in the loop.
- **No chat interface.** A prompt box with a variant grid. Conversation is the wrong shape for something
  where the user judges the output visually in under a second.
