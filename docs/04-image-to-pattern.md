# 04 — Image → Pattern

> Engine C. Runs entirely in the browser, costs nothing, and is the path most users will actually take.
> Also the shared back half of Engine B (`03-ai-integration.md` §5.3) — diffusion output re-enters this
> pipeline at stage 4.

---

## 1. The problem

Turn an arbitrary image into a 1-bit bitmap of at most 129×65 that still reads as the original thing.

That is a brutal reduction. A 1024×1024 logo becoming 32×16 pure black-and-white loses ~99.95% of its
information. Almost all of the perceived quality comes from **which** information survives, which is
decided by two choices: how the image is downsampled, and where the light/dark boundary is drawn.

Naive `drawImage` to a small canvas plus `luminance > 0.5` produces mush. Every stage below exists
because it visibly beats the naive path on real inputs.

## 2. Why client-side

| | Client | Server |
|---|---|---|
| Cost per conversion | $0 | compute + bandwidth |
| Latency per slider change | <100 ms | 300 ms+ round trip |
| Privacy | image never leaves the device | uploaded |
| Max work | 129×65 = **8,385 px** output | same |

The output is tiny. The input can be large, but the expensive stage — resampling — is a single
`drawImage` the GPU does for free. Everything downstream operates on at most 8,385 pixels, which is
nothing. There is no performance argument for a server here, and three arguments against.

**Live tuning is the feature.** Being able to drag a threshold slider and watch the pattern resolve is
what makes this usable by someone who is not a pixel artist. That interaction is only possible at
sub-100 ms latency, which rules out a round trip.

## 3. Pipeline

Ten stages. Stages 1–3 run once per uploaded image and are cached; stages 4–10 re-run on every parameter
change, which is why they operate on tiny buffers.

```
 1  Decode ─────────────┐
 2  Alpha handling      │  once per image, cached
 3  Pre-process ────────┘
 4  Resample ───────────┐
 5  Luminance           │
 6  Threshold           │  re-runs on every slider change
 7  Dither              │  (~8,385 px — sub-frame)
 8  Cleanup             │
 9  Seam repair         │
10  Preview ────────────┘
```

### Stage 1 — Decode

| Input | Handling |
|---|---|
| PNG / JPEG / WebP / GIF (first frame) | `createImageBitmap`, honouring EXIF via `imageOrientation: 'from-image'` |
| SVG | Rasterise at 4× the target's longest edge (min 512 px) before processing |
| Clipboard paste | Same path; `paste` is a first-class input |
| Drag-and-drop | Same path |

Reject > 4096×4096 with a clear message. Reject non-images. **Never** send the file anywhere.

SVG is rasterised at high resolution first because rasterising directly to 32×16 throws away the vector
precision that makes logos convert well.

### Stage 2 — Alpha handling

Transparency is meaningful for logos and it must not be silently flattened onto black.

| Mode | Behaviour | Default |
|---|---|---|
| `alpha-to-secondary` | Transparent → secondary; opaque → decided by luminance | ✔ |
| `alpha-to-primary` | Transparent → primary | |
| `composite-white` | Flatten onto white first | |
| `composite-black` | Flatten onto black first | |
| `ignore` | Discard alpha entirely | |

Threshold for "transparent": `alpha < 128`, adjustable 0–255.

`alpha-to-secondary` is the default because the overwhelmingly common case is a logo on transparency,
where the user wants the logo shape and not its bounding box.

### Stage 3 — Pre-process

Applied at full resolution, before downsampling, because these operations lose less information there.

| Control | Range | Default | Purpose |
|---|---|---|---|
| Auto-crop to content | on/off | **on** | Trim transparent/uniform borders. Enormous quality win — a logo with 30% padding wastes 30% of a 32-pixel-wide canvas. |
| Crop tolerance | 0–64 | 8 | How close to uniform counts as border |
| Brightness | −100..+100 | 0 | |
| Contrast | −100..+100 | **+15** | Slight boost helps almost every input survive thresholding |
| Gamma | 0.2–3.0 | 1.0 | |
| Unsharp amount | 0–200% | **80%** | Sharpen before downscale to preserve edges |
| Unsharp radius | 0.5–4 px | 1.5 | Scaled relative to the downsample factor |

Unsharp masking **before** downsampling is standard practice for extreme reductions and is the
difference between a readable and an unreadable 16-pixel-wide result.

### Stage 4 — Resample

Target the pattern canvas dimensions. This is where most quality is won or lost.

| Method | Use | Notes |
|---|---|---|
| **Box average** | default | Correct area-average. Best general choice for extreme downscale. |
| Lanczos-3 | detailed photos | Sharper, can ring; ringing then dithers into speckle |
| Edge-aware | logos, line art | Weights kernels toward local edges; keeps thin strokes alive |
| Nearest | already-pixel-art input | The only correct choice when input is already on-grid |

**Auto-detect already-pixel-art input.** If the source has large runs of identical colours on a regular
lattice, it is pixel art already, and any filtering destroys it. Detect the cell size by
autocorrelation over colour-change boundaries; if a confident period is found, switch to nearest and
tell the user. This matters because a common input is *someone else's pixel art*, and box-averaging it
is the worst possible handling.

**Aspect ratio.** Default is `contain` (fit, pad with secondary). Also offer `cover` (fill, crop) and
`stretch`. Padding colour follows the stage-2 alpha mode.

### Stage 5 — Luminance

Collapse RGB to one channel.

| Method | Formula | Notes |
|---|---|---|
| **OKLab L\*** | perceptual lightness | **default** — perceptually uniform |
| Rec. 709 | `0.2126R + 0.7152G + 0.0722B` | standard sRGB luma |
| Rec. 601 | `0.299R + 0.587G + 0.114B` | legacy; weights red higher |
| Max channel | `max(R,G,B)` | preserves saturated colours against dark backgrounds |
| Single channel | R, G, or B | occasionally rescues a two-colour logo |

OKLab is the default because it is perceptually uniform: equal numeric steps look like equal steps to
the eye, so the threshold lands where a human would put it. Rec. 709 systematically over-darkens
saturated blues and reds, which on a 1-bit reduction means losing a red logo against a mid-grey ground.

Convert sRGB → linear → OKLab properly; skipping the gamma step is the usual bug and it undoes the
benefit.

### Stage 6 — Threshold

| Method | Behaviour | Default |
|---|---|---|
| **Otsu** | Maximises inter-class variance. Parameter-free, works on most inputs. | ✔ |
| Manual | User-set cut point, 0–100% | |
| Mean | Mean luminance as cut point | |
| Sauvola | Local adaptive over a window; handles uneven lighting | |
| Niblack | Local adaptive, more aggressive than Sauvola | |

Otsu is the default because it requires no tuning and lands close to right on most images, which matters
for Sol (`00-overview.md` §5) who wants to upload and be done.

**Always expose a manual bias slider (−50..+50) on top of whichever method is selected.** The automatic
methods optimise a statistical criterion, not "does this look like my logo", and a nudge is the single
most-used control in the panel.

Sauvola parameters: window 15, `k = 0.34`, `R = 128`. Use it when the input has a gradient background.

### Stage 7 — Dither

Applied to the residual error after thresholding, when enabled.

| Method | Character | Tiles cleanly |
|---|---|---|
| **None** | Hard threshold. Cleanest for logos and text. | ✔ |
| **Atkinson** | Classic 1-bit Macintosh look. Propagates only 6/8 of the error, so it preserves contrast and produces open, airy texture. | approximately |
| Floyd–Steinberg | Most accurate tonally; can look noisy at this scale | approximately |
| Jarvis–Judice–Ninke | Wider diffusion, smoother, softer | approximately |
| Bayer 2×2 / 4×4 / 8×8 | Ordered, deliberately retro, strictly periodic | ✔ **exactly** |
| Blue noise | Even distribution without visible structure | ✔ with a tiled mask |

**Default is None.** Most uploads are logos, and dithering a logo makes it look damaged.

Two notes that matter for this specific domain:

- **Ordered dithers tile perfectly.** Bayer and a tiled blue-noise mask are periodic, so if the mask
  period divides the canvas dimensions the result has no seam. Error-diffusion dithers are sequential
  and inherently do not tile — they need stage 9. When "tiling" matters more than tonal accuracy, Bayer
  is the correct answer, not Floyd–Steinberg.
- **Atkinson is the right error-diffusion default** for this domain. Its reduced error propagation
  suits high-contrast two-colour output far better than Floyd–Steinberg, which muddies at low
  resolution.

**Serpentine scanning** on all error-diffusion methods, on by default — it removes the directional
worm artefacts that plain left-to-right scanning produces.

### Stage 8 — Cleanup

Small morphological fixes. At 16×8, one stray pixel is 0.8% of the image.

| Operation | Default | Purpose |
|---|---|---|
| Despeckle | **on**, min region 1 | Remove isolated single pixels (4-connected) |
| Fill holes | off, max size 1 | Remove single-pixel holes inside solid regions |
| Open (erode→dilate) | off | Remove thin protrusions |
| Close (dilate→erode) | off | Bridge small gaps |
| Edge overlay | off | Sobel edges from stage 5, unioned in — recovers outlines lost to thresholding |

Despeckle defaults on because error-diffusion dithers and aggressive thresholds both produce isolated
pixels that read as dirt rather than detail.

Edge overlay is off by default but is the rescue control for line art that thresholds into
disconnected fragments.

### Stage 9 — Seam repair

Only relevant when the pattern will tile, which for OpenFront is always. Uses the scorer from
`03-ai-integration.md` §6.

- Show the seam badge live, next to the preview.
- Offer the four repair methods from `03` §6.2.
- **Never auto-repair.** Repair alters the art; the user decides.

Error-diffusion dithers will almost always score poorly here. That is expected, and it is why the panel
suggests switching to Bayer when the user asks for a seamless result.

### Stage 10 — Preview

Three views, live:

1. **Result at 1:1**, zoomed to fit — what the bits are.
2. **Tiled 3×3** — where the seams are.
3. **Map scale** — what it looks like in game, using `PreviewRenderer` (`02-architecture.md` §3.5).

Plus a **source/result A–B toggle** so the user can flip between the original and the reduction. Judging
a 32×16 bitmap in isolation is hard; judging it against what it came from is easy.

## 4. Defaults, in one place

The parameter set that runs when a user drops in an image and touches nothing:

```jsonc
{
  "alpha":      { "mode": "alpha-to-secondary", "threshold": 128 },
  "preprocess": { "autoCrop": true, "cropTolerance": 8,
                  "brightness": 0, "contrast": 15, "gamma": 1.0,
                  "unsharpAmount": 80, "unsharpRadius": 1.5 },
  "resample":   { "method": "box", "fit": "contain", "autoDetectPixelArt": true },
  "luminance":  { "method": "oklab" },
  "threshold":  { "method": "otsu", "bias": 0 },
  "dither":     { "method": "none", "serpentine": true },
  "cleanup":    { "despeckle": true, "minRegion": 1, "fillHoles": false,
                  "open": false, "close": false, "edgeOverlay": false },
  "seam":       { "autoRepair": false }
}
```

These are tuned for the dominant case: a clan logo on transparency, converted to a small canvas. The
presets below cover the other common cases.

## 5. Presets

One click, because most users will not touch ten sliders.

| Preset | Changes from default |
|---|---|
| **Logo / flag** | (the default) |
| **Photo** | contrast +30, dither Atkinson, despeckle off, resample Lanczos |
| **Line art** | edge overlay on, contrast +40, unsharp 120% |
| **Seamless texture** | dither Bayer 4×4, autoCrop off, fit stretch |
| **Already pixel art** | resample nearest, unsharp 0, contrast 0, despeckle off |
| **High contrast** | threshold Otsu, contrast +60, despeckle on, fill holes on |

## 6. Performance

Budget: **under 100 ms** from parameter change to updated preview, so slider drags feel continuous.

- Stages 1–3 are cached per image. Changing a threshold does not re-decode a 4 MP PNG.
- Stages 4–10 work on ≤8,385 pixels. Straightforward TypeScript over `Uint8Array` is comfortably fast
  enough — no WASM, no workers needed.
- Coalesce parameter changes through `requestAnimationFrame`; a slider drag produces one recompute per
  frame, not one per input event.
- Only if stage 3 becomes a bottleneck on large inputs: move it to an `OffscreenCanvas` in a worker. Do
  not build that until measurement demands it.

Determinism is required: identical parameters and identical input must produce identical output, so the
pipeline is testable. Seed all randomness (`dots` jitter, blue noise) explicitly.

## 7. Testing

| Test | Assertion |
|---|---|
| Determinism | Same input + params → byte-identical output, 100 runs |
| Golden images | 12 reference inputs (logo, photo, line art, existing pixel art, transparent PNG, gradient…) → committed expected outputs |
| Pixel-art detection | Correctly identifies the 31 fixtures rendered at 4× as already-pixel-art |
| Ordered dither tiling | Bayer 4×4 on a canvas whose dimensions are multiples of 4 → seam score 0 |
| Despeckle | A single isolated pixel is removed; a 2-pixel pair is not |
| Otsu | Matches a reference implementation on a known histogram |
| OKLab | Round-trips sRGB→OKLab→sRGB within tolerance; matches published test vectors |
| Alpha modes | Each of the five modes produces the expected result on a half-transparent test image |
| Performance | Full stage 4–10 recompute at 129×65 completes in <16 ms |

The golden-image set is the one that catches regressions in perceived quality. Store the expected
outputs as `patternData` strings, not PNGs — they are short, diffable, and reviewable in a pull request.
