# 05 — UI / UX

> The reference tool, [Pattern Utility](https://brayflex.github.io/openfront-utility/), gets the
> interaction model substantially right and the community already knows it. Pattern Forge keeps its
> shape and adds two panels. Departing from a layout users already have muscle memory for needs a
> reason; "I would have done it differently" is not one.

---

## 1. What the reference does, and what we keep

Observed from the live tool:

- Dense **top toolbar**: Pencil · Circle · Shape · Line · Fill · Shade · Cut · Copy · Paste · Undo ·
  Redo · Select · Deselect · rotate/flip · Invert · Clear
- Second row: Width · Height · Pattern Scale (1× 2× 4×) · Zoom · Grid/Center/Ruler · Main/Test canvas
- **Left flyout** size slider (1–9) that appears for size-aware tools
- **Right panel**: live preview on top, colour controls and a long preset list below
- Top-right actions: Export · Import · JSON · Console · Preview Link · Submit
- **State encoded in the URL hash** — `#<patternData>?primary=…&secondary=…`

Kept as-is: the toolbar composition, the size flyout, the dual Main/Test canvas, the URL-hash sharing,
the primary/secondary swap, the preset list, and the overall three-region layout.

Changed: light theme becomes theme-aware (§8); the preview panel becomes two explicit modes (flat and
map-scale, per `02-architecture.md` §3.5) rather than one ambiguous view; two new panels are added.

## 2. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ✦ Pattern Forge   [tools ······························]  [Invert] [Clear]  Export  │
│                                                                              Import  │
│                   W:[ 16] H:[  8]  Scale:[1× 2× 4× 8×]  Zoom:[− 100% +]      Share   │
│                   Grid ▢  Center ▢  Ruler ▢   ⟨Main⟩ ⟨Test⟩                  Submit  │
├───┬──────────────────────────────────────────────────┬───────────────────────────────┤
│ S │                                                  │  PREVIEW    ⟨Flat⟩ ⟨Map⟩      │
│ i │                                                  │  ┌─────────────────────────┐  │
│ z │                                                  │  │                         │  │
│ e │              editing canvas                      │  │   3×3 tiled repeats     │  │
│   │              (wire:ignore — TS engine)           │  │                         │  │
│ 9 │                                                  │  └─────────────────────────┘  │
│ · │                                                  │  Seam: ● Seamless   [Repair]  │
│ 5 │                                                  ├───────────────────────────────┤
│ · │                                                  │  ✦ AI                    12 ⬡ │
│ 1 │                                                  │  ┌─────────────────────────┐  │
│   │                                                  │  │ describe a pattern…     │  │
│   │                                                  │  └─────────────────────────┘  │
│   │                                                  │  ⟨Auto⟩ ⟨Geometric⟩ ⟨Art⟩     │
│   │                                                  │           [ Generate ]        │
│   │                                                  │  ┌────┬────┬────┬────┐        │
│   │                                                  │  │ v1 │ v2 │ v3 │ v4 │        │
│   │                                                  │  └────┴────┴────┴────┘        │
│   │                                                  ├───────────────────────────────┤
│   │                                                  │  ⬆ IMAGE      [drop or paste] │
│   │                                                  ├───────────────────────────────┤
│   │                                                  │  COLOURS      ⇄ Swap          │
│   │                                                  │  Primary ▨   Secondary ▨      │
│   │                                                  │  ▸ Team simulation            │
│   │                                                  │  ▾ Presets  …                 │
└───┴──────────────────────────────────────────────────┴───────────────────────────────┘
```

Right column is scrollable and its sections are collapsible. Collapse state persists in
`localStorage` — Rin will collapse AI permanently, Sol will collapse everything but Image.

## 3. The two new panels

### 3.1 AI panel

```
✦ AI                                                    12 ⬡
┌───────────────────────────────────────────────────────────┐
│ diagonal stripes with a thin gap                          │
└───────────────────────────────────────────────────────────┘
  ⟨ Auto ⟩ ⟨ Geometric ⟩ ⟨ Art ⟩                 [ Generate ]
```

- **Auto** lets the router choose (`03-ai-integration.md` §3). **Geometric** forces Engine A,
  **Art** forces Engine B. Auto is the default and will be right most of the time; the override exists
  because it will sometimes be wrong and being stuck is worse than being wrong.
- The **credit cost appears on the button before the click**: `Generate · free` for Engine A,
  `Generate · 4 ⬡` for Engine B. Never surprise someone with a charge.
- After generation, a **4-up variant grid**. Click to preview on the canvas, click again (or press
  Enter) to commit. Committing pushes an undo entry, so an AI result is never destructive.
- A line under the grid states which engine ran and offers the alternative:
  `Generated with the geometric engine · Try the art engine instead`

**Engine A results arrive in about a second and cost nothing.** That should feel instant and free,
because it is. Do not add a spinner theatre to make it feel more substantial.

For Engine B, the flow is: generate at 128×128 → the result lands in the **Image panel's** pipeline at
stage 4 (`04-image-to-pattern.md` §3), with the threshold slider live. The user tunes the reduction
themselves. This is deliberate, not a leak of implementation detail — it is the step where a human
judgement beats an automatic one.

### 3.2 Image panel

```
⬆ IMAGE
┌───────────────────────────────────────────────────────────┐
│              drop an image, or paste, or browse           │
└───────────────────────────────────────────────────────────┘
```

After a drop, it expands:

```
⬆ IMAGE                                    [source ⇄ result]
  ┌───────────┐  Preset: ⟨Logo⟩ ⟨Photo⟩ ⟨Line art⟩ ⟨Texture⟩
  │  source   │
  │ thumbnail │  Threshold  ──────●────────  auto (Otsu)
  └───────────┘  Bias       ────────●──────  0
                 Dither     ⟨None⟩ ⟨Atkinson⟩ ⟨Bayer 4×4⟩ ▾
                 Fit        ⟨Contain⟩ ⟨Cover⟩ ⟨Stretch⟩
                 ▸ Advanced  (the full stage list from doc 04)

                 [ Commit to canvas ]
```

Four controls visible, everything else behind **Advanced**. `04-image-to-pattern.md` specifies ~25
parameters; showing all of them would make the panel unusable for Sol and is unnecessary for Rin, who
will open Advanced once and then know where things are.

The result previews **live on the editing canvas** as a ghost overlay while the panel is open —
committing is what makes it real. So the user is always judging the actual output at actual size, not a
thumbnail.

## 4. Keyboard

Match Aseprite and Photoshop conventions where they exist; pixel artists have deep muscle memory and
inventing new bindings costs goodwill for nothing.

| Key | Action | | Key | Action |
|---|---|---|---|---|
| `B` | Pencil | | `Ctrl/⌘ Z` | Undo |
| `E` | Eraser (draw secondary) | | `Ctrl/⌘ ⇧ Z` | Redo |
| `G` | Fill | | `Ctrl/⌘ C/V/X` | Copy / Paste / Cut |
| `U` | Rectangle | | `Ctrl/⌘ A` | Select all |
| `L` | Line | | `Ctrl/⌘ D` | Deselect |
| `M` | Select | | `Ctrl/⌘ I` | Invert pattern |
| `X` | Swap primary/secondary | | `Ctrl/⌘ ⇧ E` | Export |
| `1`–`9` | Brush size | | `Ctrl/⌘ Enter` | Generate (AI) |
| `+` / `−` | Zoom | | `Space` (hold) | Pan |
| `Shift` (hold) | Constrain to axis / square | | `Alt` (hold) | Temporary eyedropper |
| `Tab` | Toggle right panel | | `?` | Shortcut reference |

Arrow keys nudge the selection by one pixel; with `Shift`, by eight.

## 5. Interaction details that matter at this scale

Small canvases make ordinary interactions feel wrong unless handled specifically.

- **Zoom to cursor**, not to canvas centre. At 1600% zoom, centre-anchored zoom throws the user's work
  off-screen.
- **Pixel-perfect stroke correction** on the pencil, on by default and toggleable. Freehand drags
  produce L-shaped doubled corners; the standard fix drops the corner pixel. Rin will notice
  immediately if this is missing.
- **Draw the brush cursor as the actual pixel footprint**, aligned to the grid. A generic crosshair at
  1600% zoom is useless.
- **Grid lines only at zoom ≥ 4 px/pixel**, and a heavier line every 8 pixels.
- **Clamp minimum zoom** so the canvas is never smaller than ~200 px on screen.
- **Wrap-aware drawing** (opt-in): drawing off one edge continues on the opposite edge. Since patterns
  tile, this is how you draw a seam-crossing motif without fighting the tool.
- **The Test canvas** (from the reference) is a scratchpad at the same dimensions, with one-way copy in
  each direction. Keep it — it is how people try a change without risking the real thing.

## 6. States

Every panel needs its empty, loading, error, and success state defined, or they get improvised badly.

| Context | Empty | Loading | Error |
|---|---|---|---|
| Canvas | All-primary grid, hint: "draw, describe, or drop an image" | — | — |
| AI panel | Three example prompts as clickable chips | Skeleton variant grid + engine name + elapsed seconds | Plain sentence + Retry; credits shown as refunded |
| Image panel | Drop zone | Progress only if >200 ms | "Couldn't read that image" + accepted formats |
| Variants | — | 4 skeletons | Partial results shown if some succeeded |
| Credits | "10 free today" | — | "Out of credits — free ones reset at 00:00 UTC" + Top up |
| Gallery | "Nothing saved yet" | Skeleton cards | Retry |
| Submit | Checklist of requirements | Spinner | Field-level validation errors |

Error copy rules: say what happened, say what to do, never show a stack trace or a provider error code.
If a generation failed and credits were refunded, **say so in the error message** — the refund is
invisible otherwise and users assume they were charged.

## 7. Responsive

| Width | Behaviour |
|---|---|
| ≥1280 px | Full three-region layout |
| 900–1279 px | Right panel narrows; toolbar labels drop to icons with tooltips |
| 600–899 px | Right panel becomes a bottom sheet; canvas gets full width |
| <600 px | **View / generate / browse only.** Drawing tools hidden. |

Precision pixel drawing on a phone at this density is bad enough that offering it is worse than not
offering it. Mobile gets: browse the gallery, view patterns, run AI generation, convert an image,
export, share. Everything except the drawing tools. A clear line on small screens says so and links to
open on desktop.

Touch on tablets does get drawing, with a larger hit area and an explicit pan/draw mode toggle rather
than gesture disambiguation.

## 8. Visual design

- **Theme-aware.** The reference is light-only; respect `prefers-color-scheme` and offer an override.
  Pixel artists overwhelmingly work in dark UIs, and judging a 1-bit pattern against a bright chrome is
  actively harder.
- **The canvas surround is neutral grey**, not white and not black — both bias the perception of a
  two-colour image sitting on them.
- **The UI must never use the pattern's primary/secondary colours** in its own chrome. Confusing UI
  colour with pattern colour at a glance is a real hazard when the pattern is black and white.
- Compact and dense, like the reference. This is a tool, not a landing page. Small controls, tight
  spacing, everything reachable without scrolling on a laptop.
- Monospace for `patternData`, dimensions, and coordinates.

## 9. Sharing and export

**URL hash**, keeping the reference's scheme so links stay compatible in shape:

```
/#<patternData>?primary=ffffff&secondary=000000
```

The hash is the whole state. No server round-trip, no short-link service, works logged out.
`patternData` is at most 1403 chars, well inside URL limits.

Export targets:

| Target | Output |
|---|---|
| `patternData` | The raw base64url string, one click to clipboard |
| `cosmetics.json` entry | `{ "<patternData>": { "name": "<name>" } }`, matching OpenFront's shape |
| PNG | At 1×, 4×, 8×, and at `scale`, with the current colours |
| Share link | The URL above |

## 10. Onboarding

No tour, no modal. Three example prompt chips in the AI panel and a hint line on the empty canvas.

The one thing worth an explicit explanation is **`scale`**, because it is genuinely non-obvious and
getting it wrong makes an otherwise good pattern look wrong in game. When the user changes scale, the
map preview updates and a one-line caption states the consequence:
`Each pattern pixel covers 8×8 map tiles · repeats every 128×64 tiles`.

## 11. Accessibility

- All tools reachable by keyboard; visible focus rings throughout.
- The canvas is not screen-reader-navigable pixel by pixel — that would be absurd — but it exposes an
  accessible summary: dimensions, scale, ink coverage percentage, seam status.
- Colour is never the only signal. The seam badge carries a word, not just a dot.
- Respect `prefers-reduced-motion`: no variant-grid animation, no transitions on preview updates.
- Contrast: all UI chrome meets WCAG AA. The pattern itself is user-controlled and exempt.
