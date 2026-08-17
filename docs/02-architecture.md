# 02 — Architecture

> Livewire 4 API details in this document were verified against the current Livewire 4.x documentation,
> not recalled. Directives used: `@island`, `wire:island`, `wire:ignore`, `@script`, `@assets`, and the
> `$wire` object.

---

## 1. Stack

| Layer | Choice | Notes |
|---|---|---|
| Runtime | PHP 8.3+ | |
| Framework | Laravel 12 | |
| UI | Livewire 4 | Released Jan 2026; `@island` is used heavily (§4) |
| Reactivity glue | Alpine.js | Ships with Livewire |
| Canvas engine | **TypeScript, standalone** | No framework. See §3. |
| Bundler | Vite | Laravel default |
| Styling | Tailwind CSS v4 | |
| Database | PostgreSQL 16 | MySQL 8 works; Postgres for partial indexes on the ledger |
| Cache / queue / limits | Redis | Queue driver, rate limiter, `SpendGuard` counters |
| Queue supervision | Horizon | Visibility into AI job failures |
| Auth | Laravel Socialite | Discord + Google |
| Billing | Laravel Cashier (Stripe) | Credit top-ups only, no subscriptions |
| AI | Retro Diffusion REST + an LLM | See `03-ai-integration.md` |

**Not used, deliberately:** Laravel Reverb / WebSockets. AI jobs finish in 2–10 s; a polled island
(§4.3) is dramatically less operational surface for the same perceived latency. Revisit if generation
ever becomes long-running.

## 2. The load-bearing constraint

> **Livewire must never be in the loop for a brush stroke.**

A brush drag fires pointer events at 60–120 Hz. Each one mutates one bit. Round-tripping that to PHP is
not a performance tuning problem, it is a category error — the latency floor is ~20 ms on localhost and
100 ms+ over the network, against a 8–16 ms budget.

So the canvas is a **self-contained TypeScript application** living inside `wire:ignore`, and Livewire
owns everything around it. This one decision determines most of what follows.

The interface between them is deliberately narrow. **Only the encoded pattern string crosses the
boundary** (≤1403 chars), plus two colour hexes and the canvas dimensions. Not pixel buffers, not
stroke events, not tool state.

```
┌──────────────────── Livewire 4 · server-rendered ─────────────────────┐
│                                                                       │
│  @island('toolbar')      @island('ai-panel')     @island('credits')   │
│  @island('palettes')     @island('gallery')      @island('submit')    │
│                                                                       │
│   ┌───────────────── <div wire:ignore> ─────────────────┐             │
│   │                                                     │             │
│   │   TypeScript canvas engine                          │             │
│   │   ├─ PatternCodec      ├─ ToolController            │             │
│   │   ├─ Document + undo   ├─ ImagePipeline             │             │
│   │   ├─ Renderer          └─ PreviewRenderer           │             │
│   │                                                     │             │
│   └─────────────────────────────────────────────────────┘             │
│              │                              ▲                         │
│    CustomEvent('pf:change')          $wire.$dispatch('pf:load')       │
│    → wire:pf-change="…"              → engine.load(patternData)       │
│              ▼                              │                         │
│                        payload: { patternData, width, height, scale } │
└───────────────────────────────────────────────────────────────────────┘
```

## 3. The canvas engine

Plain TypeScript, no framework, mounted once. Lives in `resources/js/engine/`.

### 3.1 Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `PatternCodec` | encode/decode base64url ↔ bit buffer (`01` §5) | — |
| `PatternDocument` | the bit buffer, dimensions, scale, dirty tracking | `PatternCodec` |
| `History` | undo/redo | `PatternDocument` |
| `Renderer` | draws the editing canvas: pixels, grid, cursor, selection | `PatternDocument` |
| `PreviewRenderer` | 1× tiled preview and map-scale preview (§3.5) | `PatternDocument` |
| `ToolController` | pointer → tool → document mutation | `PatternDocument`, `History` |
| `Tools/*` | pencil, line, rect, ellipse, fill, shade, select, move | — |
| `ImagePipeline` | image → 1-bit (`04-image-to-pattern.md`) | — |
| `SeamScorer` | wrap-edge discontinuity metric (`03` §6) | `PatternDocument` |
| `Bridge` | the only module that talks to Livewire | all of the above |

`Bridge` is the sole boundary crossing. Nothing else imports it, and it imports no Livewire types — it
speaks `CustomEvent` and a global handle. That keeps the engine testable in plain Vitest with no Laravel
running.

### 3.2 Pixel storage

`Uint8Array`, one **byte** per pixel, not one bit.

The wire format is bit-packed, but the in-memory representation should not be. Bit twiddling on every
read during a fill or a preview render is a needless cost, and 129×65 = 8,385 bytes is nothing. Pack
only in `PatternCodec.encode()`.

```ts
class PatternDocument {
  width: number; height: number; scale: number;
  pixels: Uint8Array;                 // length w*h, values 0 (primary) | 1 (secondary)

  get(x: number, y: number): 0 | 1
  set(x: number, y: number, v: 0 | 1): void
  clone(): PatternDocument
}
```

### 3.3 Undo

Snapshot-based, not command-based.

The whole document is at most 8,385 bytes. A 200-entry history is 1.7 MB worst case, and realistically
far less. Command objects would buy nothing but bugs — especially for fill and image-commit, where the
"inverse operation" is just the previous buffer anyway.

```ts
class History {
  private past: Uint8Array[] = [];
  private future: Uint8Array[] = [];
  private limit = 200;

  commit(doc: PatternDocument): void   // call ONCE per gesture, on pointerup
  undo(doc: PatternDocument): boolean
  redo(doc: PatternDocument): boolean
}
```

**Commit on gesture end, never per pixel.** A drag across 400 pixels is one undo entry. This is the
single most common mistake in pixel editors and it makes undo useless.

A resize or dimension change clears `future` and commits — dimension changes are not undoable across
resizes in v1, and the UI warns before a destructive shrink.

### 3.4 Rendering

Two canvases, stacked, in the editing area:

1. **Pixel layer** — an `ImageData` at pattern resolution, `putImageData` into an offscreen canvas, then
   `drawImage` scaled up with `imageSmoothingEnabled = false`. This is the fast path: one
   `putImageData` per frame regardless of how many pixels changed.
2. **Overlay layer** — grid lines, selection marching ants, brush cursor, rulers. Redrawn only when
   these change, which is rarely.

Render is scheduled through a single `requestAnimationFrame` coalescer. Ten mutations in one frame
produce one repaint.

Grid lines are only drawn when zoom ≥ 4 px/pixel; below that they dominate the image and hurt more than
help.

### 3.5 Previews — the correctness-critical part

Per `01-pattern-format.md` §4, the in-game sample is:

```
isPrimary( (worldX >> scale) % width, (worldY >> scale) % height )
```

with **absolute world coordinates**, primary = territory colour, secondary = border colour.

`PreviewRenderer` must therefore:

- Tile from an **absolute origin**, not from the preview viewport's top-left, and expose a "world
  offset" control so the user can see how phase changes the look. Default offset `(0,0)`.
- Apply `>> scale` **before** `%`, in that order.
- Colour with the selected **team palette** (territory/border pair), with a swap toggle, not with
  arbitrary swatches.
- Render at least a 3×3 block of pattern repeats so seams are visible by construction. A preview showing
  a single repeat hides the exact defect the preview exists to catch.

There are two preview modes:

| Mode | Shows |
|---|---|
| **Flat** | The pattern tiled at 1:1, big enough to see ≥3 repeats each way |
| **Map scale** | The pattern at `scale` magnification over a sample territory silhouette, at the zoom level the game actually renders territory |

A shared `sampleAt(worldX, worldY)` function backs both and is the *only* place the sampling formula
appears. It gets a unit test against the fixture set.

> **Reference implementation: `tools/preview_prototype.py`.** Verified against all 31 fixtures at
> ~10,000 world coordinates each, cross-checked by a deliberately independently-written oracle.
> Visual output: `docs/assets/map-preview.png`. Port `sampleAt` from that file.

#### The negative-coordinate trap

`sampleAt` must **not** use a bare `%`. JavaScript's `%` is a remainder whose sign follows the dividend;
Python's is a floor modulo whose sign follows the divisor:

```
JS:      -1 % 4  === -1        -9 % 4  === -1
Python:  -1 %  4  ==  3        -9 %  4  ==  3
```

OpenFront never hits this — `game.x(tile)` is always ≥ 0, so its `PatternDecoder` uses a bare `%`
safely. **We do not have that guarantee.** The map preview exposes a world-offset control, and panning
it left produces negative world coordinates. A naive TypeScript port of `(x >> scale) % width` would
then index before the start of the byte array and render garbage — or throw — exactly at the origin.

Every implementation routes through a floor-modulo helper:

```ts
const mod = (a: number, n: number) => ((a % n) + n) % n;

sampleAt(wx: number, wy: number): boolean {
  const px = mod(wx >> this.scale, this.width);
  const py = mod(wy >> this.scale, this.height);
  const idx = py * this.width + px;
  return (this.bytes[3 + (idx >> 3)] & (1 << (idx & 7))) === 0;
}
```

Two tests keep this honest, and both are in the prototype:

- **Origin continuity** — sampling at `wx` equals sampling at `wx + scaledWidth` for `wx` across
  `[-scaledWidth, scaledWidth)`. This is the test a bare `%` fails.
- **No behaviour change where OpenFront is defined** — `mod` and `%` produce identical results for all
  non-negative coordinates, so adding the helper cannot drift us away from the game.

## 4. Livewire composition

### 4.1 Component tree

```
PatternForge/Editor                 (full-page component, owns pattern state)
├── @island('toolbar')              tool selection, size, zoom, undo/redo triggers
├── @island('canvas')               wire:ignore — the TS engine mounts here
├── @island('preview')              flat + map preview controls
├── @island('palette')              primary/secondary, presets, team simulation
├── @island('ai', lazy: true)       prompt, engine hints, variant grid, credits
├── @island('convert')              image drop zone + pipeline sliders
└── @island('export')               patternData, JSON, share link, submit
```

Islands matter here. Without them, changing the primary colour re-renders the AI panel, the gallery, and
the credit counter. With them, a colour change repaints one island. The canvas island additionally has
`wire:ignore`, so Livewire never diffs into it at all.

`ai` is `lazy: true` — it is below the fold for most sessions and its render touches the credit balance.

### 4.2 The bridge contract

**Engine → Livewire.** The engine dispatches a bubbling `CustomEvent`; Livewire catches it with a
`wire:` listener on the root element.

```ts
// engine/Bridge.ts
export function emitChange(doc: PatternDocument) {
  el.dispatchEvent(new CustomEvent('pf:change', {
    bubbles: true,
    detail: {
      patternData: PatternCodec.encode(doc),
      width: doc.width, height: doc.height, scale: doc.scale,
    },
  }));
}
```

```blade
<div wire:pf-change="syncPattern($event.detail)">
```

**Debounce this.** The engine emits on gesture end, but image-pipeline slider drags can fire fast.
`Bridge` debounces to 400 ms trailing, and flushes immediately before export, save, or any AI call.

**Livewire → Engine.** Use `$wire.$dispatch` from a `@script` block, or call the engine handle directly:

```blade
@script
<script>
  const engine = window.PatternForge.mount($wire.$el.querySelector('#pf-canvas'));

  $wire.$on('pf:load', ({ patternData }) => engine.load(patternData));
  $wire.$on('pf:set-colors', ({ primary, secondary }) => engine.setColors(primary, secondary));
</script>
@endscript
```

`@script` runs after Livewire initialises the component and re-runs if the component is re-mounted,
which is what we want; a bare `<script>` tag does not have those guarantees.

### 4.3 AI job lifecycle

No WebSockets. A `Generation` row plus a polled island.

```
User clicks Generate
  └─ Livewire action: Editor::generate()
       ├─ authorize + reserve credits (single DB transaction, 06 §5)
       ├─ SpendGuard::check()                     ← may reject here
       ├─ dispatch GenerateJob                    ← returns immediately
       └─ set $activeGenerationId

@island('ai') renders with wire:poll.1500ms while $activeGenerationId is pending
  └─ each poll re-reads the Generation row

GenerateJob (queue: ai)
  ├─ call the engine (03-ai-integration.md)
  ├─ SpendGuard::record(actual_cost_cents)
  ├─ store result images to disk
  ├─ status = completed | failed
  └─ on failure: refund the credit reservation

Poll sees completed
  ├─ stop polling
  └─ dispatch 'pf:variants' with result URLs → engine renders the variant grid
```

Polling only runs while a generation is in flight — `wire:poll` is conditional on
`$activeGenerationId !== null`. An idle editor makes zero background requests.

Timeout: a generation still `pending` after 120 s is marked `failed` by a scheduled command, and its
credits refunded. The job itself has `$timeout = 90` and `$tries = 2`, retrying only on transport
errors, never on a 4xx from the provider.

### 4.4 Image uploads — mostly there aren't any

The default image→pattern path **does not upload anything**. The file goes into a plain
`<input type="file">` inside the `wire:ignore` region, is read with `FileReader`, drawn to an offscreen
canvas, and converted in-browser. Zero bytes to the server, zero cost, instant slider feedback.

The only time an image is uploaded is the *optional* AI-assisted conversion (`rd_pro__pixelate`), which
needs the pixels server-side to forward to the provider. That path uses Livewire's `WithFileUploads`
with explicit limits (§6.2) and deletes the temp file in the job's `finally`.

This distinction is worth guarding in review: it would be very easy to reach for `wire:model` on the
file input out of habit and silently turn a free, instant feature into a slow, costly one.

## 5. Server-side layout

```
app/
├── Livewire/
│   ├── Editor.php                  the full-page editor component
│   ├── Editor/AiPanel.php          extracted for testability
│   ├── Gallery.php
│   └── Billing/Credits.php
├── Domain/Pattern/
│   ├── PatternCodec.php            PHP twin of the TS codec (01 §5)
│   ├── PatternValidator.php        mirrors OpenFront's Zod rules (01 §2)
│   └── SeamScorer.php              PHP twin, used for server-side scoring of AI output
├── Domain/Ai/
│   ├── EngineRouter.php            picks A/B/C/D (03 §3)
│   ├── Engines/ParametricEngine.php
│   ├── Engines/DiffusionEngine.php
│   ├── Engines/EditEngine.php
│   ├── PatternDsl.php              the parametric DSL + renderer (03 §4)
│   └── RetroDiffusionClient.php    thin HTTP client, no business logic
├── Domain/Credits/
│   ├── CreditLedger.php            append-only, see 06 §5
│   └── SpendGuard.php              Redis daily ceiling, see 07 §5
└── Jobs/
    ├── GenerateJob.php
    └── EditRegionJob.php
```

`RetroDiffusionClient` stays dumb on purpose: it maps a typed request to HTTP and back, and knows
nothing about credits, seams, or routing. That makes it trivially fakeable in tests via
`Http::fake()`.

### 5.1 Codec parity

`PatternCodec` exists in **both** TypeScript and PHP and the two must agree byte-for-byte.

- TS is authoritative for interactive use (live preview, URL hash, export button).
- PHP is authoritative for storage: **every** `patternData` that reaches the database is re-validated
  and re-encoded server-side. Never trust the client's string.
- A shared fixture file, generated from `cosmetics.json`, is consumed by both test suites.
- CI runs a parity test over 1,000 seeded pseudo-random patterns (`01` §8).

## 6. Security & limits

### 6.1 Secrets

`RETRO_DIFFUSION_API_KEY` and the LLM key live in `.env`, are read only inside `Domain/Ai/*`, and are
never serialised into a Livewire component's state. Livewire snapshots are signed but **visible to the
client** — any property on a component is effectively public. Keys must never be component properties.

### 6.2 Upload limits

Applies only to the AI-assisted conversion path (§4.4):

| Limit | Value |
|---|---|
| Max file size | 8 MB |
| Accepted MIME | `image/png`, `image/jpeg`, `image/webp` |
| Max dimensions | 4096 × 4096, rejected above |
| Validation | re-decode server-side with Intervention Image; reject on failure |
| Retention | deleted in the job's `finally` block |

SVG is accepted **client-side only** (rasterised in the browser) and never uploaded — server-side SVG
parsing is an XXE and billion-laughs surface we have no reason to take on.

### 6.3 Rate limits

Beyond credits, which are the real control (`07-cost-and-abuse.md`):

| Action | Limit |
|---|---|
| Any AI generation | 20/hour/user, 5/minute/user |
| Pattern save | 60/hour/user |
| Submit for review | 5/day/user |
| Anonymous page loads | standard Laravel throttle |

### 6.4 Untrusted input

Pattern names are user-controlled and rendered in the gallery. They are constrained to `^[a-z0-9_]+$`
(`01` §2), which makes them inert, but validate on the way **in** rather than escaping on the way out.

AI prompts are user-controlled and reach an LLM. `03-ai-integration.md` §4.4 covers the injection
boundary: the LLM's output is parsed as a strict JSON schema and every numeric field is range-clamped
before it reaches the renderer. A prompt cannot cause anything except a differently-shaped pattern.

## 7. Testing strategy

| Layer | Tool | What |
|---|---|---|
| TS codec, pipeline, seam scorer | Vitest | Fixtures, property tests, pipeline determinism |
| TS engine interaction | Vitest + happy-dom | Tool gestures produce expected buffers; undo granularity |
| PHP codec | Pest | Same fixtures |
| Cross-language parity | Pest, invoking `node` | 1,000 seeded patterns, TS output === PHP output |
| Livewire components | Pest + Livewire test helpers | Island updates, credit reservation, error states |
| AI engines | Pest + `Http::fake()` | Routing decisions, retry, refund-on-failure |
| Credit ledger | Pest | Concurrency: two simultaneous spends cannot overdraw |
| End-to-end | Playwright | Draw → export → validate; upload → convert → commit |

The credit-ledger concurrency test matters more than it looks. It is the one place where a race
produces free money.

## 8. Deployment

Single VPS is sufficient; nothing here needs scale-out.

```
nginx → php-fpm (Laravel)
        ├─ queue worker: default   (1 process)
        ├─ queue worker: ai        (2 processes, higher timeout)
        ├─ Horizon
        └─ scheduler (timeout sweeper, daily counter reset)
redis
postgres
```

Generated images go to local disk behind a signed-URL route, or S3-compatible storage if that becomes
inconvenient. They are cache, not source of truth — the `patternData` string is. A generated image can
be deleted at any time without data loss; the pattern it produced lives in the database.

## 9. Open items

Things this document deliberately does not settle, flagged so they are not forgotten:

1. **Submit-for-review destination.** The reference tool has a submit flow. Where it posts, and whether
   Pattern Forge may post there too, needs confirming with the OpenFront maintainers before Phase 6.
   Until then, the submit button produces a copyable `cosmetics.json` entry.
2. **LLM provider for the parametric engine.** `03-ai-integration.md` specifies the contract, not the
   vendor. Any model that reliably emits constrained JSON works; pick on cost at build time.
3. **Whether PHP needs `SeamScorer`.** Only if we score AI output server-side before returning variants.
   Cheaper to score in the browser. Decide in Phase 4; the module is listed above so the option stays
   open, and it should be deleted if unused rather than left as dead code.
