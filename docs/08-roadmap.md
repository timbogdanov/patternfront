# 08 — Roadmap

> Build order, with acceptance criteria concrete enough to execute against without re-reading the other
> docs. Each phase ends in something demonstrable.
>
> Phases are ordered by **risk retired per unit of work**, not by user-visible progress. The codec and
> the preview come first because everything downstream is worthless if they are wrong, and both are
> cheap to get right early and expensive to fix late.

---

## Phase 0 — Scaffold

Laravel 12 + Livewire 4 + Vite + Tailwind v4 + Postgres + Redis, running locally.

- [ ] `laravel new pattern-forge`, Livewire 4, Horizon, Pest
- [ ] Vite configured for TypeScript under `resources/js/engine/`
- [ ] Vitest configured, running against the engine directory
- [ ] Docker Compose or Herd/Valet for Postgres + Redis
- [ ] CI: `pest`, `vitest`, `eslint`, `pint`, `phpstan` on every push

**Done when:** a blank Livewire page renders, and both test runners execute an empty suite green in CI.

---

## Phase 1 — The codec

Nothing else can be trusted until this is exact. No UI in this phase.

- [ ] `PatternCodec` in TypeScript (`01-pattern-format.md` §5)
- [ ] `PatternCodec` in PHP, same behaviour
- [x] ~~Fixture generator script: `cosmetics.json` → `tests/fixtures/patterns.json`~~ — **done**,
      `tools/gen-fixtures.py`. Emits 31 patterns with dimensions, scale, ink coverage and
      run-length-encoded pixel data, so tests can assert decoded *content*, not just header parsing.
      It refuses to write if any source pattern fails validation.
- [ ] All eight error guards from `01` §5.1, each with a distinct type
- [ ] Trailing-bit zeroing verified in both implementations

**Acceptance:**
- All **31** fixtures round-trip byte-identically in TS. *(Verified achievable — the reference
  implementation in `01` §5 already does this, 31/31.)*
- All 31 round-trip byte-identically in PHP.
- Cross-language parity over 1,000 seeded pseudo-random patterns: TS output === PHP output.
- Dimension sweep `{2,3,7,8,9,128,129} × {2,3,7,8,9,64,65}` round-trips.
- 129×65 encodes to exactly 1403 characters.
- `ABMIVVU` decodes to 4×4, scale 3, alternating columns.
- Each guard triggers its own error type.

---

## Phase 2 — Editor core

The manual tool, standing entirely on its own. If this is not good, no amount of AI rescues it — Rin
(`00-overview.md` §5) will reject the product here.

- [ ] `PatternDocument`, `History`, `Renderer`, `ToolController`
- [ ] Tools: pencil, eraser, line, rectangle, ellipse, fill, select, move
- [ ] Undo/redo, snapshot-based, **one entry per gesture**
- [ ] Zoom to cursor, pan, grid at zoom ≥4, brush cursor showing the real footprint
- [ ] Pixel-perfect stroke correction
- [ ] Canvas resize with a warning on destructive shrink
- [ ] Keyboard shortcuts (`05-ui-ux.md` §4)
- [ ] Livewire shell + `wire:ignore` island + Alpine bridge (`02` §4.2)
- [ ] URL-hash state (`05` §9)

**Acceptance:**
- A 400-pixel drag produces exactly one undo entry.
- Drawing at 1600% zoom stays at 60fps (measured, not assumed).
- Reloading a URL hash reproduces the pattern and both colours exactly.
- The Livewire bridge round-trips a pattern with no data loss, debounced.

---

## Phase 3 — Previews

The correctness-critical piece. Do this before AI, so AI output is judged against a truthful preview.

> **De-risked.** `tools/preview_prototype.py` implements `sampleAt` and verifies it against all 31
> fixtures at ~10,000 world coordinates each, against an independently-written oracle. It also caught
> the negative-coordinate trap that would have broken the world-offset control in a TS port
> (`02` §3.5). Port from that file. Visual output: `docs/assets/map-preview.png`.

- [x] ~~`sampleAt(worldX, worldY)` — the single implementation of the sampling formula~~ — **prototyped
      and verified**; port to TS
- [ ] Floor-modulo helper, with the origin-continuity test (`02` §3.5)
- [ ] Flat preview, ≥3×3 repeats
- [ ] Map-scale preview with absolute world-coordinate tiling and a world-offset control
- [ ] Team-colour simulation (territory/border), swap toggle
- [ ] `SeamScorer` + the three-state badge (`03-ai-integration.md` §6.1)
- [ ] Export: `patternData`, `cosmetics.json` entry, PNG at 1×/4×/8×/scale

**Acceptance:**
- For all 31 fixtures, `sampleAt` output matches a reference implementation of
  `PatternDecoder.isPrimary` at 10,000 sampled world coordinates each. *(The Python prototype achieves
  31/31; the TS port must reproduce it.)*
- Sampling is continuous through negative world coordinates — the bare-`%` regression test.
- Scale changes visibly alter the map preview and the caption reports the correct repeat period.
- `checkerboard` scores **Seamless**; a deliberately seam-broken pattern scores **Visible seam**.
- Exported `cosmetics.json` entries validate against OpenFront's own Zod schema.

---

## Phase 4 — Image → pattern

The first AI-shaped feature, and it needs no provider, no auth, and no credits. Ship it before anything
that costs money.

- [ ] `ImagePipeline`, all ten stages (`04-image-to-pattern.md` §3)
- [ ] Defaults exactly as `04` §4
- [ ] Six presets (`04` §5)
- [ ] Drop / paste / browse; SVG rasterisation
- [ ] Already-pixel-art auto-detection
- [ ] Live ghost overlay on the canvas; commit pushes an undo entry
- [ ] Basic + Advanced control split (`05` §3.2)

**Acceptance:**
- Full stage 4–10 recompute at 129×65 completes in **<16 ms**.
- Identical input + parameters produce byte-identical output over 100 runs.
- Twelve golden inputs produce their committed expected `patternData`.
- The 31 fixtures, rendered at 4×, are all detected as already-pixel-art.
- Bayer 4×4 on dimensions that are multiples of 4 yields seam score 0.

---

## Phase 5 — Accounts & credits

Infrastructure before anything spends money. Unglamorous and non-negotiable.

- [ ] Socialite: Discord + Google; `oauth_identities`; nullable password
- [ ] `credit_entries` ledger; `CreditLedger` service (`06-data-model.md` §5)
- [ ] Lazy daily free grant
- [ ] `SpendGuard` with fail-closed behaviour (`07` §5)
- [ ] Rate limiters (`07` §7)
- [ ] Cashier + credit packs + webhook grant
- [ ] Credit balance UI

**Acceptance:**
- Two concurrent spends against a balance of 1 credit: exactly one succeeds. *(The test that matters.)*
- A replayed Stripe webhook grants credits exactly once.
- With Redis down, `SpendGuard::check()` throws and no generation dispatches.
- The §4 margin assertion in `07` passes against the live config.
- Free credits reset at 00:00 UTC and do not accumulate.

---

## Phase 6 — AI generation

> **Substantially de-risked.** A complete, tested reference implementation already exists in
> `tools/dsl_prototype.py`: all 15 primitives, composition ops, validation, LCM sizing, and the seam
> scorer. `tools/dsl_demo.py` renders 28 programs and asserts 28/28 tile exactly.
> **Port it rather than reimplementing from prose** — building it corrected three errors in `03`
> (the `diagonal` period formula, the missing `text.leading`, and the entire seam metric).

- [ ] `PatternDsl` — port schema, validator with clamping, and renderer from `tools/dsl_prototype.py`
- [ ] All 15 shape primitives, each with a declared period
- [ ] Tiling guarantee: LCM sizing + period-nudge fallback (`03` §4.5)
- [x] ~~System prompt~~ — **done**, `resources/prompts/router.md`; 18 examples, all verified
      executable by `tools/verify-prompt.py`
- [ ] `EngineRouter` calling that prompt
- [ ] `RetroDiffusionClient`, `Http::fake()`-able
- [ ] `GenerateJob`, polled island, timeout sweeper, refund-on-failure
- [ ] Diffusion output → Phase 4 pipeline at stage 4 (`03` §5.3)
- [ ] AI panel: engine override, cost-before-click, 4-up variant grid

**Acceptance:**
- Every Engine A output satisfies the structural tiling check (`03` §6.1 A) when `autoSize` is on —
  the ported implementation reproduces the prototype's 28/28.
- "diagonal stripes with a thin gap" routes to parametric and produces `03` §4.6's program.
- A malformed LLM response falls through to diffusion without a user-visible error.
- A provider 4xx refunds credits and shows a human message; a 5xx retries once then refunds.
- An adversarial prompt set produces only valid bitmaps — no path to code execution or extra spend.
- A generation still pending at 120 s is swept to failed and refunded.

---

## Phase 7 — AI region edit

- [ ] Selection → `rd_pro__edit` with the region as `input_image`
- [ ] Result composited back into the selection only
- [ ] Pre-edit snapshot written to `pattern_versions`

**Acceptance:**
- Pixels outside the selection are bit-identical before and after.
- Undo restores the pre-edit state in one step.

---

## Phase 8 — Persistence, gallery, submit

- [ ] `patterns`, `pattern_versions`, `submissions` (`06` §3–4, §8)
- [ ] Save / load / fork; visibility controls
- [ ] Public gallery with pagination
- [ ] Submit flow producing a `cosmetics.json` entry

**Acceptance:**
- Every saved `pattern_data` is re-validated and re-encoded server-side.
- Denormalised `width`/`height`/`scale` always agree with the decoded `pattern_data`.
- A forked pattern records `forked_from_id`.

> **Blocked item:** the real submit destination is unconfirmed (`02` §9). Until the OpenFront
> maintainers confirm where submissions should go and whether Pattern Forge may post there, Submit
> produces a copyable entry and marks the row `submitted` locally. The table shape does not change when
> a destination exists — only `external_ref` starts being populated.

---

## Phase 9 — Polish & launch

- [ ] Responsive behaviour (`05` §7), including the mobile no-drawing line
- [ ] Theme-aware light/dark
- [ ] Empty / loading / error states for every panel (`05` §6)
- [ ] Accessibility pass (`05` §11)
- [ ] Monitoring dashboard (`07` §10)
- [ ] Quality eval: 40-prompt set + automated metrics (`03` §8)
- [ ] Attribution to Aotumuri & BrayFlex and to OpenFront (`00` §10)
- [ ] Privacy policy covering ledger retention (`06` §10)

**Acceptance:** the six success criteria in `00-overview.md` §6, each demonstrated rather than asserted.

---

## Sequencing notes

**Why the codec is first.** A codec bug found in Phase 8 invalidates every pattern in the database. In
Phase 1 it costs an afternoon. It also happens to be fully testable against 31 real fixtures with no UI
in existence, which is a rare gift.

**Why previews precede AI.** Judging AI output through an incorrect preview means tuning prompts against
a lie. The map-scale sampling formula is subtle enough (`01` §4) that it will be wrong on the first
attempt, and it is much better to discover that in Phase 3.

**Why image→pattern precedes generation.** It costs nothing to run, needs no provider integration, no
auth and no credits — and it is the feature the plan's originating request called out explicitly. It
also builds the reduction pipeline that Engine B depends on (`03` §5.3), so Phase 6 gets it for free.

**Why credits precede AI.** Wiring billing after generation works means running unmetered against a live
key at some point. Do not.

## Rough sizing

Relative, not calendar time — actual pace depends on how much of this is being done in one sitting.

| Phase | Size | Risk |
|---|---|---|
| 0 Scaffold | XS | low |
| 1 Codec | S | low — fully specified, fully testable |
| 2 Editor core | **L** | medium — the most hand-written interaction code |
| 3 Previews | S | low — **was** M/high; `sampleAt` is prototyped and fixture-verified |
| 4 Image pipeline | **L** | medium — many stages, but each is small and testable |
| 5 Accounts & credits | M | medium — concurrency and webhooks |
| 6 AI generation | M | medium — **was** L/high; the tested prototype and prompt cut both |
| 7 Region edit | S | low — builds on 6 |
| 8 Persistence | M | low, one blocked item |
| 9 Polish | M | low |

**Both original high-risk phases are now retired.** Phase 3 and Phase 6 each had their risk concentrated
in a single function — `sampleAt` and the DSL renderer. Both now exist as tested Python prototypes, and
writing them produced four corrections that reading the spec would not have caught:

| Found by | Correction |
|---|---|
| DSL prototype | Seam metric flagged 17 of 28 correctly-tiling patterns — whole metric rewritten (`03` §6.4) |
| DSL prototype | `diagonal` period formula was loose (`03` §4.3) |
| DSL prototype | `text` had no leading, rendering as texture rather than lettering |
| Preview prototype | Bare `%` breaks on negative world coordinates in JS (`02` §3.5) |

**Phase 2 (editor core) is now the largest remaining risk** — not because it is subtle, but because it
is the most hand-written interaction code and the least amenable to fixture-driven testing.

## Deferred

Explicitly not in v1, recorded so they are decisions rather than omissions:

- Animated / multi-frame patterns — not supported by the format
- Full-colour editing — out of scope (`00` §4)
- A fine-tuned pixel-art model — 31 examples is not a dataset (`03` §9)
- Real-time collaboration
- Reverb / WebSockets — polling is sufficient at these latencies (`02` §1)
- A native Aseprite plugin
- Pattern marketplace / paid patterns
