# 01 — The OpenFront Pattern Format

> **Everything in this document was read out of OpenFront's source and verified by decoding real data.**
> Nothing here is inferred. Where a claim comes from source, the file and line are cited.
>
> Source of truth:
> - `OpenFrontIO/src/core/PatternDecoder.ts` — the decoder
> - `OpenFrontIO/src/core/CosmeticSchemas.ts` — the validation limits
> - `OpenFrontIO/src/core/game/GameView.ts` — how it renders in game
> - `OpenFrontIO/resources/cosmetics/cosmetics.json` — 31 real patterns, used as fixtures
>
> If OpenFront changes upstream, **re-run the verifier** before trusting this document:
>
> ```
> python3 tools/verify-docs.py [path/to/OpenFrontIO]
> ```
>
> It decodes every pattern in `cosmetics.json` and checks each factual claim made here and in
> `07-cost-and-abuse.md`. Exit code 0 means the docs still match the source. As of writing: **22 checks,
> all passing.**

---

## 1. The wire format

A pattern is a byte string, base64url-encoded **without padding**.

```
┌────────┬──────────────────────────────────────────────────────────────┐
│ byte 0 │ version — must be 0, else reject                             │
├────────┼──────────────────────────────────────────────────────────────┤
│ byte 1 │ bits 0-2  scale (0..7)                                       │
│        │ bits 3-7  low 5 bits of (width - 2)                          │
├────────┼──────────────────────────────────────────────────────────────┤
│ byte 2 │ bits 0-1  high 2 bits of (width - 2)                         │
│        │ bits 2-7  (height - 2)                                       │
├────────┼──────────────────────────────────────────────────────────────┤
│ byte 3 │ bitmap, row-major, LSB-first within each byte                │
│  ...   │   bit == 0  →  PRIMARY colour                                │
│        │   bit == 1  →  SECONDARY colour                              │
└────────┴──────────────────────────────────────────────────────────────┘
```

Decoding the header (`PatternDecoder.ts:53-63`):

```ts
const version = bytes[0];              // must be 0
const scale  =  bytes[1] & 0x07;                                    // 0..7
const width  = (((bytes[2] & 0x03) << 5) | ((bytes[1] >> 3) & 0x1f)) + 2;
const height = (( bytes[2] >> 2) & 0x3f) + 2;
```

Note the **`+ 2` bias** on both dimensions. Width gets 7 bits (0..127 → **2..129**), height gets 6 bits
(0..63 → **2..65**). A 1×1 pattern is unrepresentable, which is fine — it would be a solid colour.

Payload length is `ceil(width * height / 8)`, so total byte length is:

```
total = 3 + ((width * height + 7) >> 3)
```

The decoder checks `bytes.length - 3 >= expectedBytes` (`PatternDecoder.ts:67`). It checks for **at
least** enough bytes — trailing slack is tolerated. Our encoder emits exact-length payloads; our
validator accepts slack to stay compatible.

### 1.1 Bit addressing

For pattern-space coordinate `(px, py)` (`PatternDecoder.ts:22-32`):

```ts
idx       = py * width + px
byteIndex = idx >> 3
bitIndex  = idx & 7
isPrimary = (bytes[3 + byteIndex] & (1 << bitIndex)) === 0
```

Two things trip people up here, both worth stating plainly:

- **LSB-first.** Index 0 is bit `0x01` of byte 3, not bit `0x80`. Getting this backwards mirrors every
  byte horizontally in groups of 8 — subtle enough to ship by accident.
- **Zero means primary.** The sense is inverted relative to the intuition that "1 = on = foreground". A
  freshly zeroed buffer is an all-primary pattern.

## 2. Validation limits

From `CosmeticSchemas.ts`:

| Field | Rule | Line |
|---|---|---|
| `patternData` | base64url, **≤ 1403 chars**, must decode without throwing | `24-45` |
| `name` | `/^[a-z0-9_]+$/`, ≤ 32 chars | `19-22` |
| `colorPalette` | `{ name: string, primaryColor: string, secondaryColor: string }` | `47-51` |

**The 1403 cap and the dimension bits agree exactly**, which is a useful cross-check that the format is
being read correctly:

```
max dims        129 × 65      = 8385 bits
payload         ceil(8385/8)  = 1049 bytes
total           3 + 1049      = 1052 bytes
base64url       ceil(1052×4/3) = 1403 chars   ← matches the schema cap exactly
```

So the maximum canvas is **129 × 65**. Any UI that offers larger is producing invalid patterns. The
reference tool defaults to 128×64, comfortably inside.

## 3. Worked example — decoding `ABMIVVU`

Do this by hand once; it makes every later bug obvious.

```
base64url "ABMIVVU"
  A=0  B=1  M=12  I=8  V=21  V=21  U=20
  → 000000 000001 001100 001000 010101 010101 010100
  → bytes: 00000000  00010011  00001000  01010101  01010101
           0x00      0x13      0x08      0x55      0x55

version = 0x00                                  ✓
scale   = 0x13 & 0x07              = 3          → each pixel covers 8×8 world tiles
width   = ((0x08 & 3) << 5 | (0x13 >> 3) & 0x1f) + 2
        = ((0)      << 5 | 2)                + 2 = 4
height  = ((0x08 >> 2) & 0x3f) + 2 = 2 + 2      = 4

payload = 4×4 = 16 bits = 2 bytes = 0x55 0x55
0x55 LSB-first = 1,0,1,0,1,0,1,0

row 0: idx 0..3  → 1 0 1 0   →  S P S P
row 1: idx 4..7  → 1 0 1 0   →  S P S P
row 2: idx 8..11 → 1 0 1 0   →  S P S P
row 3: idx 12..15→ 1 0 1 0   →  S P S P
```

Alternating **columns** — i.e. vertical stripes. And its name in `cosmetics.json` is **`stripes_v`**. ✓

## 4. How it renders in game — and why the preview must match

This is the detail most likely to make a plausible-looking preview wrong.

`GameView.territoryColor` (`GameView.ts:321-330`):

```ts
territoryColor(tile?: TileRef): Colord {
  if (tile === undefined || this.decoder === undefined) return this._territoryColor;
  const isPrimary = this.decoder.isPrimary(this.game.x(tile), this.game.y(tile));
  return isPrimary ? this._territoryColor : this._borderColor;
}
```

Three consequences, all of which the preview must honour:

**a) The pattern tiles in absolute world coordinates.** The arguments are `game.x(tile)` and
`game.y(tile)` — the tile's position on the *map*, not its position within the player's territory. Two
players with the same pattern in different places see it phased differently. A territory does not start
at pattern origin. **A preview that anchors the pattern to the territory's bounding box is wrong.**

**b) Primary is territory, secondary is border.** Not arbitrary swatches. The "team colour simulation"
in the reference tool exists precisely because these are the player's real colours.

**c) Scale is applied by bit-shift, then wrapped by modulo** (`PatternDecoder.ts:23-24`):

```ts
const px = (x >> this.scale) % this.width;
const py = (y >> this.scale) % this.height;
```

`>>` before `%`. So the effective tile in world space is `(width << scale) × (height << scale)`, exposed
by `scaledWidth()` / `scaledHeight()`. At `scale: 3`, a 4×4 pattern occupies 32×32 world tiles.

Because wrapping is a plain modulo with **no** requirement that dimensions be powers of two, a pattern
whose left edge doesn't meet its right edge will show a hard seam every `width << scale` tiles. Seam
quality is a real, visible property — see `03-ai-integration.md` §6.

## 5. Reference implementation

Encoder, inverse of §1. This is the behaviour both the TypeScript and PHP implementations must match.

```python
def encode(width, height, scale, bits):     # bits: width*height ints, 0=primary
    w, h = width - 2, height - 2
    b1 = (scale & 0x07) | ((w & 0x1f) << 3)
    b2 = ((w >> 5) & 0x03) | ((h & 0x3f) << 2)
    payload = bytearray((width * height + 7) >> 3)
    for i, v in enumerate(bits):
        if v:
            payload[i >> 3] |= 1 << (i & 7)
    raw = bytes([0, b1, b2]) + bytes(payload)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
```

### 5.1 Required guards

Both implementations must reject, with a distinguishable error each:

| Condition | Error |
|---|---|
| `version != 0` | `UnsupportedVersion` |
| `len(bytes) < 3` | `TruncatedHeader` |
| `len(bytes) - 3 < ceil(w*h/8)` | `TruncatedPayload` |
| `width < 2 or width > 129` | `DimensionOutOfRange` |
| `height < 2 or height > 65` | `DimensionOutOfRange` |
| `scale < 0 or scale > 7` | `ScaleOutOfRange` |
| `len(b64) > 1403` | `PayloadTooLarge` |
| non-base64url characters | `MalformedEncoding` |

Note `width`/`height` **cannot** go out of range when decoding — the bit widths make it impossible. The
guard exists for the *encode* path, where a caller could pass a 200-wide canvas.

### 5.2 Trailing-bit hygiene

When `width * height` is not a multiple of 8, the final payload byte has unused high bits. **Always zero
them.** Two encoders that disagree on garbage bits produce different base64 for identical patterns,
which breaks deduplication, caching by `patternData`, and the fixture test. The `bytearray(n)`
zero-initialisation above handles this; a PHP implementation using `str_repeat("\0", n)` does too.

## 6. Fixtures — all 31 real patterns

Every pattern in `resources/cosmetics/cosmetics.json`, decoded. **All 31 round-trip byte-identically**
through decode → re-encode with the §5 implementation: 31/31, zero failures.

This table is the test suite. Both the TS and PHP codecs must reproduce it exactly.

| # | name | patternData | W×H | scale | bytes | role_group |
|---:|---|---|---:|---:|---:|---|
| 1 | `vertical_bars` | `AAoACQ` | 3×2 | 2 | 4 | donor |
| 2 | `stripes_v` | `ABMIVVU` | 4×4 | 3 | 5 | — |
| 3 | `stripes_h` | `ABMIDw8` | 4×4 | 3 | 5 | — |
| 4 | `horizontal_stripes` | `AAEYAwA` | 2×8 | 1 | 5 | donor |
| 5 | `checkerboard` | `ABMIpaU` | 4×4 | 3 | 5 | — |
| 6 | `mini_cross` | `AHEYA8AMMDAMwAPAAzAMDDADwA` | 16×8 | 1 | 19 | donor |
| 7 | `diagonal_stripe` | `AHEYAYACQAQgCBAQCCAEQAKAAQ` | 16×8 | 1 | 19 | donor |
| 8 | `mountain_ridge` | `AHEYAAAYGDw8fn7__35-PDwYGA` | 16×8 | 1 | 19 | donor |
| 9 | `scattered_dots` | `AHEYAAACIAAAAAAAAAAACBAAAA` | 16×8 | 1 | 19 | donor |
| 10 | `circuit_board` | `AHEYw8PDwwwMDAwwDDAMw8PDww` | 16×8 | 1 | 19 | donor |
| 11 | `-w-` | `AHEYAAAAAAAAAkCCQUQiLnQWaA` | 16×8 | 1 | 19 | donor |
| 12 | `choco` | `AFIoAAABOEAHgkAc-AN_4AMcgAAA` | 12×12 | 2 | 21 | — |
| 13 | `shells` | `AHEgzGfznzu43XPoL2fMn_O4O3fdL-g` | 16×10 | 1 | 23 | donor |
| 14 | `evan` | `ALIUAAAAnsRIgiRZjuRpAiNJHiNJAAAA` | 24×7 | 2 | 24 | creator |
| 15 | `diagonal` | `AHE4AQACAAQACAAQACAAQACAAAABAAIABAAIABAAI…` | 16×16 | 1 | 35 | donor |
| 16 | `cross` | `AHE4AYACQAQgCBAQCCAEQAKAAYABQAIgBBAICBAEI…` | 16×16 | 1 | 35 | donor |
| 17 | `sword` | `AHI4AOAAkACIAEQAIgARjAhUBCgCKAHQACgB1AILA…` | 16×16 | 2 | 35 | donor |
| 18 | `sparse_dots` | `AHE4AQEAAAAAAAAAAAAAAAAAAAEBAAAAAAAAAAAAA…` | 16×16 | 1 | 35 | donor |
| 19 | `white_rabbit` | `AHE4AAAAAKAAUAFQAVABCC4EUCQgJCAEIDgm0BBwD…` | 16×16 | 1 | 35 | donor |
| 20 | `contributor` | `AMo0AAAAAAAAAAAAAIAAJAACEAIIQCAgAAGCAAQgC…` | 27×15 | 2 | 54 | — |
| 21 | `cursor` | `AJhMAAAABACAAQBwAAAeAMAHAPgBAH8A4B8A_AeA_…` | 21×21 | 0 | 59 | donor |
| 22 | `t_rex` | `AJlMAAAAAP8A8D8A9gfA_wD4HwAfAOAfAn5A4A8Y_…` | 21×21 | 1 | 59 | donor |
| 23 | `hand` | `AJhYAAAAGACABACQAAASAEACAMgBAMkBIMkAJCngJ…` | 21×24 | 0 | 66 | donor |
| 24 | `radiation` | `AMFYAAAAAAAAAAzAADgAB_ABPuAH-IE_8Af_4T_8h…` | 26×24 | 1 | 81 | donor |
| 25 | `goat` | `AKFwAAAADMAABSiAAgVAoQBQKAA0CwB6AfDhAwIAQ…` | 22×30 | 1 | 86 | donor |
| 26 | `openfront` | `AAIiAAAAAAAAAAAAAAAAAAAAAIDD8YnweTiiD5FIY…` | 66×10 | 2 | 86 | creator |
| 27 | `openfront_qr` | `AMpkAAAA8DfCnyAQgnTl0KVrvS5d73UJkinIX1V_A…` | 27×27 | 2 | 95 | donor |
| 28 | `embelem` | `AAqFAAACAAAAOAAAAOADAAAAHwAAAPgAAEDABwQAw…` | 35×35 | 2 | 157 | donor |
| 29 | `grogu_head` | `AMlNAAAAAAAAAAAAAPAfAACAHwDwgAcAAMQf4ADgA…` | 59×21 | 1 | 158 | donor |
| 30 | `cats` | `ALF1AAAAAAAAABABAAAAAACwAQAAAAAA8AEAAAAAI…` | 56×31 | 1 | 220 | donor |
| 31 | `grogu` | `AMl9AAAAAAAAAAAAAPAfAACAHwDwgAcAAMQf4ADgA…` | 59×33 | 1 | 247 | donor |

*Long strings truncated with `…` for readability. The test fixture file must contain them in full —
generate it from `cosmetics.json` rather than transcribing from this table.*

### 6.1 What the fixture data tells us

- **Every limit is respected.** Max width observed 66, max height 35 — both far below the 129×65 ceiling.
  Real patterns are much smaller than the format allows. Design the UI for the common case (16×8 to
  32×32), not the maximum.
- **Every `scale` from 0 to 3 is used.** Small patterns lean on high scale (`stripes_v` is 4×4 at
  scale 3 → 32×32 world tiles); large pictorial patterns use scale 0–1. Scale is not decoration; it is
  how a 4-byte pattern covers meaningful map area.
- **Sizes cluster.** 16×8 (six patterns) and 16×16 (five) dominate. These should be one-click presets.
- **`role_group` gates access.** Values seen: `donor`, `creator`, and absent. Not part of the format —
  it is entitlement metadata in `cosmetics.json`, irrelevant to encoding but relevant to the submit flow.

## 7. Licensing

OpenFront is **AGPL-3.0**. Pattern Forge must **not** vendor or copy OpenFront source.

What we do instead: this document describes the format, and we write clean-room implementations in
TypeScript and PHP from the description. Formats and protocols are not themselves copyrightable; the
specific expression in `PatternDecoder.ts` is. The `cosmetics.json` values used as test fixtures are
short factual data strings, used for interoperability testing.

Practical rules:

- Do not copy `PatternDecoder.ts` into the repo, in any language, as a transliteration.
- Do generate the fixture JSON from `cosmetics.json` at build time, and keep the generator script in the
  repo rather than the OpenFront file itself.
- Credit OpenFront and link to its repo in the About panel.

If Pattern Forge is ever distributed as anything other than a hosted service, revisit this with someone
qualified. AGPL's network clause applies to *OpenFront's* code, which we are not running — but the
boundary deserves a real check before any code is redistributed.

## 8. Test plan for the codec

`08-roadmap.md` Phase 1 ships all of this before anything else is built.

| Test | Assertion |
|---|---|
| **Fixture round-trip** (TS) | All 31 fixtures: `encode(decode(x)) === x` |
| **Fixture round-trip** (PHP) | Same 31, same result |
| **Cross-language parity** | For 1,000 pseudo-random patterns, TS and PHP produce identical base64 |
| **Dimension sweep** | Every `(w,h)` in `{2,3,7,8,9,128,129} × {2,3,7,8,9,64,65}` round-trips |
| **Scale sweep** | `scale` 0..7 round-trips at fixed dimensions |
| **Trailing bits** | Two patterns differing only in unused high bits encode identically |
| **Boundary** | 129×65 encodes to exactly 1403 chars |
| **Rejection** | Each §5.1 guard triggers its own distinct error |
| **Known-value** | `ABMIVVU` decodes to 4×4/scale 3/alternating columns (§3) |

The cross-language parity test is the one that catches real bugs. Seed it deterministically so failures
reproduce.
