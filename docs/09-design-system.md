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
exactly that reason, defaulting to 2× on high-DPI displays. PatternFront does the same.

Every length in the stylesheet is `rem`, and `html{font-size:calc(10px * var(--ui))}`
drives the lot. So `1.1rem` reads as "11px at 1×" and one token resizes the whole
interface. The artwork view scales too — `Z() = zoom * uiScale` — so the app scales as
a single piece rather than the chrome growing around a fixed canvas.

The control sits in the top bar (1× · 1.5× · 2× · 2.5× · 3×) and persists to
`localStorage`. **Default is 2×.**

| Scale | Bars | Buttons | Font | Rail | Columns |
|---|---|---|---|---|---|
| 1× | 24px | 18px | 11px | 26px | 152 / 190 |
| 1.5× | 36px | 27px | 16px | 39px | 228 / 285 |
| **2×** | **48px** | **36px** | **22px** | **52px** | **304 / 380** |
| 2.5× | 60px | 45px | 28px | 65px | 380 / 475 |
| 3× | 72px | 54px | 33px | 78px | 456 / 570 |

Above 2× the side columns start to crowd the canvas on a 1440px window — `Tab` collapses
both and is the intended companion to the larger scales.

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
├ left column 152px · colour, palette, canvas, options
├ stage · dominant, the only thing that grows
└ right column 190px · preview, layers
dock 24px · frames + status on one line
```

`Tab` collapses both columns (`body.zen`) for a near-fullscreen canvas.
One continuous docked column per side — no floating cards, no gaps, no rounding;
sections separated by 1px rules.

## Anti-patterns

Every one of these was tried and rejected:

- Glass, blur, translucency
- Radii above 2px
- Light grey chrome
- Floating cards with gaps
- Gradients and drop shadows for depth
- A second accent colour
