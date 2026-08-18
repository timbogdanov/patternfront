# PatternFront

A 1-bit pattern editor for [OpenFront.io](https://openfront.io) territory patterns — the small
tiling bitmaps that mark out a player's territory. Desktop app for macOS and Windows, and the
same editor runs in a browser.

![PatternFront](docs/assets/desktop.png)

Patterns are two colours and at most 129×65 pixels, which sounds trivial and is not: they tile
against absolute world coordinates, so a seam that looks fine in the editor can read as a defect
across a whole territory. PatternFront draws them, previews them tiled at real map scale, and
exports the exact `patternData` string the game takes.

## What it does

- **Draw** — pencil, eraser, fill, line, rectangle, ellipse, symmetry, wrap-around, brush sizes
- **Grab a shape** — 8-connected flood select; drag a heart or a sword around and it backfills behind itself
- **54 stamps** — symbols, animals, nature, objects, UI marks, and small tiles for texture work
- **Layers and frames** — onion skinning, animated GIF export
- **Import an image** — median-cut quantisation to 2 colours with Floyd–Steinberg, Atkinson or Bayer dithering
- **50 duotone presets** — every pair checked for enough luma and hue separation to read at map scale
- **Live tiled preview** — see the seams before the game does
- **Export** — PNG, sprite sheet, animated GIF, and OpenFront `patternData` (or JSON for `cosmetics.json`)

On the desktop it is a real application, not a wrapped web page: native menus, `.patternfront`
documents with Open/Save/Save As, double-click to open from Finder or Explorer, recent files,
exports through native Save dialogs, remembered window position, and an unsaved-changes prompt
that will not let you lose work.

## Install

Grab a build from [Releases](https://github.com/timbogdanov/patternfront/releases).

**These builds are unsigned.** Paying Apple and Microsoft for certificates is not something this
project does yet, so both systems will warn you the first time:

- **macOS** — right-click the app → **Open** → **Open**. Once, then never again.
- **Windows** — SmartScreen shows "Windows protected your PC" → **More info** → **Run anyway**.

If that is not acceptable to you, build it yourself — it takes one command, below.

> **Known issue building on recent macOS.** `npm run dist` can fail at the DMG step with
> `hdiutil: convert failed - Resource temporarily unavailable`, from the `dmgbuild` copy that
> electron-builder vendors. The `.zip` targets are unaffected, and the app inside them is
> identical — `npm run dist -- --mac zip` gets you a working build. Unzip and drag to
> Applications.

## Run from source

Needs Node 20+ and Python 3.10+ (Python is only for the generators and the verification suite).

```sh
npm install
npm start          # run the desktop app
npm run verify     # run every check
npm run dist       # build installers for the current platform
```

There is no build step for the editor itself. `app/patternfront.html` is one self-contained file
with no dependencies, no bundler and no network access — open it directly in a browser and it
works. The desktop build loads that same file; nothing is forked.

## How it is put together

```
app/patternfront.html   the entire editor — markup, styles, logic, stamps
electron/               main process, preload bridge, menus, document handling
tools/                  generators and the verification suite
docs/                   design documents
tests/fixtures/         the codec corpus
```

The renderer feature-detects `window.pfNative`. Without it — in a browser — every native path is
skipped and the file behaves exactly as it always did. That is asserted by tests, not assumed.

## Verification

`npm run verify` runs nine suites. They exist because this project kept getting things subtly
wrong in ways that only mechanical checking caught — a seam metric that flagged correct patterns,
a modulo that goes negative in JavaScript but not Python, an unguarded `localStorage` read that
killed the app before first paint in any sandboxed frame.

| Suite | What it proves |
|---|---|
| codec corpus | 1125 patterns across every width 2–129, height 2–65 and all 8 scales round-trip byte-exactly |
| editor codec | the shipping JavaScript agrees with that corpus byte for byte |
| DSL prototype | 28 parametric programs tile without seams, measured not eyeballed |
| map-scale sampling | `sampleAt` matches an independent oracle, including at negative world coordinates |
| UI design rules | no shadows, no gradients, no radius above 2px, no light chrome — the design system, enforced |
| stamp library | every stamp is a valid pattern, uniquely named, and legible at 1× |
| editor behaviour | ~80 assertions running the editor's real functions in a sandbox |
| desktop smoke test | Electron actually launches and the editor comes up, headless |
| docs vs OpenFront | *optional* — cross-checks the format docs against a local game checkout |

The last one needs an OpenFront clone and **skips loudly** without one. It never silently passes.

## The pattern format

Documented in [`docs/01-pattern-format.md`](docs/01-pattern-format.md), verified against the real
game data. Briefly: base64url, a 3-byte header carrying scale and dimensions, then LSB-first bits
where **bit 0 is the primary colour**. Maximum 129×65, which is 1403 base64 characters — a number
this repo's corpus hits exactly.

## Status, honestly

The editor and the desktop app are real and work. The AI features described in
[`docs/03`](docs/03-ai-integration.md), [`04`](docs/04-image-to-pattern.md) and
[`07`](docs/07-cost-and-abuse.md) — text-to-pattern, AI region editing, hosted credits — are
**designed and not built**. The image importer in the app today is ordinary quantisation and
dithering, which is deterministic, offline and needs no API key. Those documents are a plan, not
a description.

## Licence

MIT — see [LICENSE](LICENSE).

This project deliberately ships **no OpenFront assets**. Their `cosmetics.json` patterns are
CC BY-SA 4.0 and include third-party characters they cannot sublicense onward, so none of them
are redistributed here. If you have a local OpenFront checkout you can generate them for your own
use in one command. See [NOTICE](NOTICE).

PatternFront is an independent tool. It is not affiliated with or endorsed by OpenFront LLC.
