# 00 — Overview

> **Status:** design complete, no code written.
> **Read order:** this file → `01-pattern-format.md` → `02-architecture.md` → the rest in any order.
> `08-roadmap.md` is the build order.

---

## 1. What this is

**Pattern Forge** is a web app for designing, generating, and publishing **OpenFront territory
patterns** — the 1-bit tiling bitmaps that colour a player's territory in
[OpenFront.io](https://openfront.io).

It is a superset of the existing community tool
[Pattern Utility](https://brayflex.github.io/openfront-utility/) by Aotumuri & BrayFlex: everything that
tool does (draw, preview, export, submit), plus three things it does not do:

1. **Upload an image → get a pattern.** Drop in a logo, flag, or photo; tune the conversion live;
   commit it to the canvas.
2. **Describe a pattern → get a pattern.** Type "diagonal stripes with a thin gap" or "a wolf head" and
   get real, tiling, 1-bit output.
3. **Select a region → describe a change.** Redraw part of a pattern without touching the rest.

## 2. Why it needs to exist

Territory patterns are the main way OpenFront players express identity, but authoring them is hard in a
way that is disproportionate to the result:

- The canvas is tiny (max 129×65) and **1-bit** — no shading to hide mistakes behind. Every pixel is a
  decision.
- Patterns **tile**. A design that looks great flat can seam badly in game, and you don't find out until
  you see it on the map.
- Patterns render at a **power-of-two scale in absolute world coordinates**, so what you draw is not
  what you see in game (see §4 of `01-pattern-format.md`).
- Most players are not pixel artists. The blank-canvas problem is severe at this size.

Every one of those is a problem AI is well suited to, *if* it is pointed at the right sub-problem.
`03-ai-integration.md` argues that "the right sub-problem" is usually **not** image diffusion.

## 3. Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | Anyone can produce a usable pattern in under 2 minutes without drawing | Time from landing to a pattern they keep |
| G2 | Never ship a pattern that seams badly | Seam score surfaced before export; repair offered |
| G3 | Preview is truthful | Pixel-identical to `GameView.territoryColor` output |
| G4 | Free path is genuinely useful | Editing + image→pattern cost 0 credits, forever |
| G5 | AI spend is bounded | Hard daily ceiling; a bug cannot produce a surprise bill |
| G6 | Exports are always valid | Server-side validation mirrors OpenFront's Zod schema exactly |

## 4. Non-goals

Explicitly out of scope. Revisit only after v1 ships.

- **Full-colour pixel art.** OpenFront patterns are 1-bit. Building a general sprite editor would
  quadruple the surface area and serve a different audience.
- **Animation / sprite sheets.** Patterns are static.
- **Being an Aseprite replacement.** We handle one narrow format extremely well.
- **A social network.** A gallery of public patterns, yes. Follows, comments, feeds, no.
- **Mobile drawing.** Mobile gets view, browse, and generate. Precision pixel drawing on a phone at
  this density is not worth building for v1.

## 5. Who it's for

**Kade — the OpenFront regular.** Plays several times a week, wants a clan pattern that reads at map
scale. Not an artist. Will type a prompt, iterate on variants, and export. Cares that it looks good in
game, not about the editor's tooling depth.

**Rin — the pattern author.** Has made patterns by hand in the existing tool. Wants precision tools,
keyboard shortcuts, and no AI in the way. Will use image→pattern as a *starting point*, then hand-fix
every pixel. Will abandon the tool instantly if AI output is force-fed or if the drawing tools are worse
than what they already have.

**Sol — the clan organiser.** Wants their logo as a pattern. Has a PNG. Wants to upload it, tune two
sliders, and be done. Never opens the drawing tools.

The design consequence: **the AI must be additive, never mandatory.** Every AI feature drops its result
onto a normal editable canvas, and the manual toolset must stand on its own for Rin.

## 6. Success criteria for v1

Ship when all of these hold:

1. A hand-drawn pattern round-trips through export → OpenFront's own validator without error.
2. The map-scale preview is pixel-identical to in-game rendering for all 31 shipped patterns.
3. Image→pattern converts a typical clan logo to something recognisable at 32×32, client-side, in
   under 100 ms per parameter change.
4. Text→pattern produces a seam-free tiling result for geometric prompts **without** calling a
   diffusion model.
5. A logged-out visitor can draw, convert an image, preview, and export — no account, no credits.
6. The daily spend ceiling provably halts generation when hit (tested, not assumed).

## 7. Glossary

| Term | Meaning |
|---|---|
| **Pattern** | A 1-bit bitmap, 2..129 wide × 2..65 tall, plus a `scale`, encoded to base64url. |
| **`patternData`** | The base64url string. Max 1403 chars. This *is* the pattern as far as OpenFront is concerned. |
| **Primary / Secondary** | The two colours. Bit `0` = primary, bit `1` = secondary. In game these are the player's **territory** and **border** colours. |
| **Scale** | Power-of-two magnification, 0–7. `scale: 3` means each pattern pixel covers 8×8 world tiles. |
| **Seam** | The join where a pattern wraps. A pattern tiles by modulo, so left edge meets right edge. |
| **Seam score** | Our metric for how visible that join is. Lower is better. See `03-ai-integration.md` §6. |
| **Engine** | One of the four AI backends (Parametric, Diffusion, Conversion, Edit). |
| **Credit** | The unit users spend on AI actions. Local operations cost zero. |
| **Fixture** | One of the 31 real patterns from OpenFront's `cosmetics.json`, used as a codec test vector. |

## 8. Decisions already locked

Recorded here so they don't get relitigated mid-build.

| Decision | Choice | Rationale |
|---|---|---|
| Domain | OpenFront 1-bit patterns only | Depth over breadth; see non-goals |
| Backend | Laravel 12 + Livewire 4 | Owner's stack preference |
| Canvas | Standalone TypeScript, **not** Livewire | 60fps interaction cannot round-trip to PHP (`02` §3) |
| Image conversion | Client-side | Max 8,385 px; free, instant, live-tunable |
| AI provider | Retro Diffusion | Native `rd_fast__1_bit` two-colour style + seamless tiling flags |
| Billing | Free daily tier + Stripe credits | Owner hosts the API keys |
| Auth | Socialite (Discord, Google) | Discord is where the OpenFront community lives |

## 9. Document map

| Doc | Answers |
|---|---|
| `01-pattern-format.md` | What exactly is a pattern, byte for byte? |
| `02-architecture.md` | How is the app put together, and what runs where? |
| `03-ai-integration.md` | How does the AI actually produce good patterns? |
| `04-image-to-pattern.md` | How does an uploaded image become 1-bit? |
| `05-ui-ux.md` | What does the user see and touch? |
| `06-data-model.md` | What's in the database? |
| `07-cost-and-abuse.md` | What does it cost, and how is it bounded? |
| `08-roadmap.md` | In what order do we build it? |

## 10. Attribution

The reference tool, [Pattern Utility](https://brayflex.github.io/openfront-utility/), is by **Aotumuri &
BrayFlex**. Pattern Forge takes its interaction model as a starting point because it is well designed and
the community already knows it. That lineage should be credited in the app's About panel.

OpenFront itself is AGPL-3.0. Pattern Forge reads its pattern format and reimplements the codec; it does
not vendor OpenFront code. `01-pattern-format.md` §7 covers the licensing consequence.
