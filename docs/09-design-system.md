# 09 — Design System

PatternFront is styled on **Aseprite's dark theme**, transcribed from
`aseprite/data/extensions/aseprite-theme/dark/theme.xml` rather than approximated.

This file exists because the visual direction was reset four times. The rules below are
enforced mechanically by `tools/verify-ui.py`, which fails the build if they erode.

## Why Aseprite

It's the tool the audience already uses. Familiarity beats novelty for a production
tool, and it settles a question that repeated redesigns could not.

## Tokens

Aseprite's own id is kept against each value so the mapping stays auditable.

| Token | Hex | Aseprite id | Use |
|---|---|---|---|
| `--face` | `#2c2c30` | `face` | panel chrome, the default surface |
| `--raised` | `#41444a` | `background` | inputs, buttons, list rows |
| `--well` | `#202125` | `editor_face` | recessed areas, tracks |
| `--void` | `#000000` | `editor_view_face` | behind the sprite, dividers |
| `--workspace` | `#333333` | `workspace` | status areas |
| `--edge` | `#575b61` | `check_hot_face` | 1px borders, hover |
| `--text` | `#c0c0c0` | `text` | primary |
| `--dim` | `#7d7d7d` | `tab_normal_text` | secondary |
| `--mute` | `#636d79` | `status_bar_text` | tertiary, status |
| `--accent` | `#e1b85f` | `selected` | selection, active tool |
| `--accent-hi` | `#eec877` | — | accent hover |
| `--accent-ink` | `#41444a` | `selected_text` | text on accent |
| `--link` | `#6e9adb` | `link_text` | links, info |
| `--danger` | `#c75a68` | `flag_active` | destructive |

Note Aseprite's dark accent is **gold**, not blue. Blue is reserved for links.

This one was reversed once and reversed back. A revision moved `--accent` to
OpenFront's own blue (`#2962ff`) on the reasoning that the tool is for OpenFront.
The result was two blues eight hue-degrees apart doing unrelated jobs — selection
and links — and a design document that disagreed with both the stylesheet and the
checker. Chrome belongs to the audience, which lives in Aseprite; OpenFront fidelity
is carried by the format, the codec and the map-scale preview, not by the accent.
`tools/verify-ui.py` now fails on `#2962ff` so the round trip is not repeated.

## Hard rules

- **Radius 0–2px.** Nothing rounder, anywhere.
- **No shadows, no blur, no translucency, no decorative gradients.** Flat fills.
- **1px hard borders** carry every boundary.
- **No neutral surface lighter than `--raised`.** Text may be light; chrome may not.
- **One accent.** Gold for selection, blue only for links.

Two deliberate exceptions, both checked for:

- `.tr` uses linear-gradients to draw the transparency checkerboard — a functional
  pattern, which Aseprite also draws.
- The accent family is exempt from the surface-luma rule. Selection is meant to be loud.

## Interface scale

Aseprite's native density is very tight and it ships a **UI Scale** preference for
exactly that reason, defaulting to 2× on high-DPI displays. PatternFront carries the
same preference at a lower default, for the reason given below.

Every length in the stylesheet is `rem`, and `html{font-size:calc(10px * var(--ui))}`
drives the lot. So `1.1rem` reads as "11px at 1×" and one token resizes the whole
interface. The artwork view scales too — `Z() = zoom * uiScale` — so the app scales as
a single piece rather than the chrome growing around a fixed canvas.

The control sits in the top bar (1× · 1.5× · 2× · 2.5× · 3×) and persists to
`localStorage`. **Default is 1.5×** — 2× was the original default and crowded the
canvas once the preview took a column of its own.

Columns are left / preview / right.

| Scale | Bars | Buttons | Font | Rail | Columns |
|---|---|---|---|---|---|
| 1× | 24px | 18px | 11px | 26px | 152 / 240 / 190 |
| **1.5×** | **36px** | **27px** | **16px** | **39px** | **228 / 360 / 285** |
| 2× | 48px | 36px | 22px | 52px | 304 / 480 / 380 |
| 2.5× | 60px | 45px | 28px | 65px | 380 / 600 / 475 |
| 3× | 72px | 54px | 33px | 78px | 456 / 720 / 570 |

Above 1.5× the columns start to crowd the canvas on a 1440px window — `Tab` collapses
them and is the intended companion to the larger scales.

## Density

Base values, scaled from Aseprite's own `dimensions` block, quoted at 1×.

| Element | Aseprite | Here |
|---|---|---|
| Bars (top, dock) | `context_bar_height` 18 | 24px |
| Buttons | 16–18 | 18px |
| List row | — | 22px |
| Tool button | — | 22px in a 26px rail |
| Font | — | 11px UI, 10px labels |
| Spacing | — | 2 / 4 / 6 / 8 |

## Layout

```
top bar 24px
├ rail 26px · tools, always visible
├ left column 152px · colour, duotone, stamps, palette
├ stage · dominant, the only thing that grows
├ preview column 240px · preview and its controls
└ right column 190px · layers
dock 24px · frames + status on one line
```

The preview holds its own column rather than stacking under the layers panel. It is
the surface a pattern is actually judged on — it is the only place the duotone
appears at all — and sharing a column made it the first thing squeezed.

`Tab` collapses all three columns and their gutters (`body.zen`) for a near-fullscreen
canvas. Each boundary is a drag handle (`.gut`) that resizes the column it sits against
and resets on double-click; the widths live in `--wL` / `--wP` / `--wR` so a drag and a
scale change move the same numbers.

One continuous docked column per region — no floating cards, no gaps, no rounding;
sections separated by 1px rules.

## States

Tokens and density were specified from the start; states were not, and drifted into
inline hex. Every one below is a token, and `tools/verify-ui.py` fails on a literal
colour used where one of these belongs.

| State | Treatment | Token |
|---|---|---|
| Rest | `--raised` fill, `--edge-dim` border | — |
| Hover | fill and border both go to `--edge` | `--edge` |
| Active / pressed | fill drops to `--well` | `--well` |
| Selected / on | `--accent` fill, `--accent-ink` text | `--accent`, `--accent-ink` |
| Focus (keyboard) | 1px `--accent` outline, no offset | `--accent` |
| Disabled | text to `--well`, default cursor, no hover | `--well` |
| Success | text only, never a fill | `--ok` |
| Error | text only, never a fill | `--danger` |

Two rules that are easy to get wrong:

- **Status is text, not chrome.** A valid or over-length pattern says so in `--ok` or
  `--danger` text. It never tints a panel, because a coloured panel competes with the
  artwork, which is the only thing in the window whose colour carries meaning.
- **Focus is not hover.** Hover is a fill change; focus is an outline. A control that
  showed focus by filling would be indistinguishable from selection.

## Anti-patterns

Every one of these was tried and rejected:

- Glass, blur, translucency
- Radii above 2px
- Light grey chrome
- Floating cards with gaps
- Gradients and drop shadows for depth
- A second accent colour
