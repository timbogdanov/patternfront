# Contributing

## Getting set up

```sh
git clone https://github.com/timbogdanov/patternfront
cd patternfront
npm install
npm start
```

Node 20+ and Python 3.10+. The Python side is stdlib only — no pip install, no virtualenv.

## Before you open a pull request

```sh
npm run verify
```

This has to pass. CI runs the same script, plus a headless launch of the desktop app.

## How the project is laid out

`app/patternfront.html` is the whole editor — markup, styles and logic in one file with no build
step and no dependencies. That is deliberate: it opens in a browser by double-clicking, and the
desktop app loads the identical file. There is no second copy to keep in sync.

Native behaviour is feature-detected behind `window.pfNative`. If you add something desktop-only,
guard it with `native()` and make sure the browser path still works — there is a test that boots
the code with no `pfNative` at all and fails if anything reaches for it.

## Things that will fail CI

**Generated files must match their generator.** Stamps and codec fixtures are produced by scripts;
editing the output by hand is caught. Change the source and re-run:

```sh
python3 tools/gen-stamps.py --emit      # then paste the STAMPS block
python3 tools/gen-codec-fixtures.py
```

**The design rules are enforced.** `tools/verify-ui.py` fails the build on border radius above
2px, box shadows, blur, decorative gradients, chrome lighter than `--raised`, and stylesheet
lengths in `px` instead of `rem`. These are not suggestions; the visual direction was reset
several times before they existed. See `docs/09-design-system.md`.

**No OpenFront assets.** The repository ships none, for licensing reasons set out in
[NOTICE](NOTICE), and there is a gate that fails if any reappear.

## Adding a stamp

Stamps are ASCII art in `tools/gen-stamps.py` — edit them as pictures, not as hex:

```python
art("nature", "acorn", """
................
......####......
.....######.....
...
""")
```

Run `python3 tools/gen-stamps.py`. The generator rejects anything under 8% or over 75% ink
(invisible, or a blob) and renders every surviving shape to `docs/assets/stamps.png`.

**Look at that contact sheet.** It is the step that decides what ships. A 16×16 one-bit icon that
you know is a snail often reads as a camera to everyone else. Several shapes have been cut from
this library for exactly that reason, after two or three attempts each. Cutting one is a normal
outcome, not a failure.

## Tests

`tools/verify-behaviour.js` runs the editor's **real** functions by lifting them out of the HTML
and executing them in a sandbox. Nothing in it is a reimplementation — if you change a function,
the test runs your changed version. Add cases there rather than writing a parallel copy of the
logic.

## Style

Match what is around you. The codebase is dense and commented where the reasoning is not obvious
from the code — why a modulo has to be floor-mod, why a track is `minmax(0,1fr)`. Comments that
restate the line above are noise; comments that record a trap are the valuable kind.

## Reporting bugs

Include your OS and app version, and say what you expected. The version is in the About panel —
`PatternFront → About` on macOS, `Help → About` on Windows. If it is a rendering problem, a
screenshot saves a great deal of time.
