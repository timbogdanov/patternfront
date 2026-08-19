#!/usr/bin/env python3
"""
Enforce the PatternFront design rules on app/patternfront.html.

The visual direction has been reset several times. These are the rules from
docs/09-design-system.md, checked mechanically so they can't quietly erode:

    radius 0-2px · no shadows · no blur · no decorative gradients
    no light SURFACES · Aseprite's token values present · one accent

Deliberate exceptions, each justified:
  * `.tr` uses two linear-gradients to draw the transparency checkerboard.
    That's a functional pattern, not decoration — Aseprite draws one too.
  * Light hexes are fine as TEXT (--text, --dim, --mute, --link, --ok).
    The rule is about surfaces. This checks `background` specifically.

Run:  python3 tools/verify-ui.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "patternfront.html")

# Aseprite dark theme — data/extensions/aseprite-theme/dark/theme.xml
TOKENS = {
    "--face": "#2c2c30",      # face
    "--raised": "#41444a",    # background
    "--well": "#202125",      # editor_face
    "--void": "#000000",      # editor_view_face
    "--workspace": "#333333", # workspace
    "--edge": "#575b61",      # check_hot_face
    "--text": "#c0c0c0",      # text
    "--dim": "#7d7d7d",       # tab_normal_text
    "--mute": "#636d79",      # status_bar_text
    "--accent": "#e1b85f",    # selected
    "--accent-hi": "#eec877",  # accent hover
    "--accent-ink": "#41444a", # selected_text
    "--link": "#6e9adb",      # link_text
    "--danger": "#c75a68",    # flag_active
}
# NEUTRAL surfaces may not be lighter than --raised. Luma via Rec.709.
# The accent is exempt: Aseprite's own `selected` is a bright gold, and
# selection is meant to be loud. The rule is about chrome, not highlights.
MAX_SURFACE_LUMA = 0.30
ACCENT_FAMILY = {"e1b85f", "eec877"}

fails: list[str] = []


def chk(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def decode_stamp_w(data: str) -> int:
    """Width of a stamp's patternData — its canvas's intrinsic pixel width."""
    import base64
    b = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return (((b[2] & 3) << 5) | ((b[1] >> 3) & 31)) + 2 if len(b) >= 3 else 0


def luma(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main() -> int:
    if not os.path.exists(APP):
        print(f"missing {APP}")
        return 2
    src = open(APP, encoding="utf-8").read()
    css = "".join(re.findall(r"<style>(.*?)</style>", src, re.S))
    js = "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))

    print("=== structure ===")
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', src))
    used = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", js))
    chk("every $(id) resolves to an element", not (used - ids), str(sorted(used - ids)))

    void = {"br", "hr", "img", "input", "meta", "link", "path", "rect", "circle",
            "ellipse", "line", "polyline", "polygon", "source", "area", "col"}
    body = re.sub(r"<script>.*?</script>", "", src, flags=re.S)
    body = re.sub(r"<style>.*?</style>", "", body, flags=re.S)
    stack, bad = [], []
    for m in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(/?)>", body):
        closing, name, _, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in void or selfclose:
            continue
        if not closing:
            stack.append(name)
        elif not stack or stack[-1] != name:
            bad.append(name)
        else:
            stack.pop()
    chk("HTML tags balance", not stack and not bad, str(stack + bad))

    print("\n=== design rules ===")
    for prop in ("backdrop-filter", "box-shadow", "radial-gradient", "filter:blur"):
        n = len(re.findall(re.escape(prop), css))
        chk(f"no {prop}", n == 0, f"{n} occurrence(s)")

    # gradients: only the transparency checkerboard is allowed
    grads = re.findall(r"[^\n{;]*linear-gradient[^\n;]*", css)
    stray = [g for g in grads if "25%" not in g]  # the checker uses 25%/75% stops
    chk("gradients only for the transparency checker", not stray,
        f"{len(grads)} total, {len(stray)} stray")

    # Lengths are rem now (1rem = 10px at 1x), so 0.2rem == 2px.
    radii = [float(v) for v in re.findall(r"border-radius:\s*([\d.]+)rem", css)]
    radii += [float(v) for v in re.findall(r"border-radius:\s*(\d+)px", css)]
    chk("no border-radius above 2px (0.2rem)", all(r <= 0.2 for r in radii),
        f"max {max(radii) if radii else 0}")

    # SURFACES only — text is allowed to be light
    surfaces = re.findall(r"background(?:-color)?:\s*([^;}\n]+)", css)
    lit = []
    for decl in surfaces:
        for h in re.findall(r"#([0-9a-fA-F]{6})", decl):
            low = h.lower()
            # #ffffff is the artwork paper; the accent family is the selection colour
            if low in ACCENT_FAMILY or low == "ffffff":
                continue
            if luma(h) > MAX_SURFACE_LUMA:
                lit.append("#" + h)
    chk("no neutral chrome surface lighter than --raised", not lit, str(sorted(set(lit))))

    accents = {h.lower() for h in re.findall(r"#([0-9a-fA-F]{6})", css)}
    chrome_accents = accents & ACCENT_FAMILY
    chk("one accent family only", len(chrome_accents) <= 2, str(sorted(chrome_accents)))

    print("\n=== Aseprite tokens ===")
    flat = css.replace(" ", "")
    for tok, val in TOKENS.items():
        chk(f"{tok} = {val}", f"{tok}:{val}" in flat)

    print("\n=== image import ===")
    for cid, label in (("ids", "dither strength"), ("is", "saturation"),
                       ("ith", "threshold"), ("iReset", "reset")):
        chk(f"{label} control present", f'id="{cid}"' in src)
    chk("import colours default to 16, not the document palette",
        'id="ic" min="2" max="64" value="16"' in src)
    chk("import defaults are declared independently", "const IDEF=" in js)

    print("\n=== layout ===")
    chk("vertical tool rail", 'id="rail"' in src and "buildRail" in js)
    chk("Tab collapses both rails", "toggleZen" in js and "body.zen .col{display:none}" in css)
    chk("column widths default to 152 / 240 / 190 @1x",
        "--wL:15.2rem" in css and "--wP:24rem" in css and "--wR:19rem" in css)
    chk("24px bars @1x", "height:2.4rem" in css)

    print("\n=== interface scale ===")
    chk("root font-size drives the scale", "font-size:calc(10px * var(--scale))" in css)
    chk("--scale token declared", re.search(r"--scale:\s*[\d.]+", css) is not None)
    chk("--ui is a length, not the multiplier (no name collision)",
        re.search(r"--ui:\s*[\d.]+rem", css) is not None
        and not re.search(r"--ui:\s*[\d.]+;", css))
    chk("default scale is 1.5x",
        re.search(r"--scale:\s*1\.5", css) is not None
        and "store.get('pf.ui')||1.5" in js)
    chk("scale control present", 'id="uiScale"' in src and "applyUiScale" in js)
    chk("scale persists", "store.set('pf.ui'" in js)
    chk("artwork scales with the UI", "const Z=()=>zoom*uiScale" in js)
    leftover = len(re.findall(r"[*+(]zoom(?![A-Za-z])", js))
    chk("no display geometry still using raw zoom", leftover <= 1,
        f"{leftover} (1 expected: the wheel-handler value compare)")
    # Strip comments first — prose is allowed to say "px" while explaining why
    # a rule exists; the rule is about declarations.
    css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    stray_px = [l.strip() for l in css_nc.split("\n")
                if "px" in l and "@media" not in l and "font-size:calc" not in l]
    chk("stylesheet is rem-based", not stray_px, str(stray_px[:3]))

    print("\n=== behaviour ===")
    chk("opens on our own wordmark, not OpenFront's",
        "PATTERNFRONT_WORDMARK" in js and "docFromPattern" in js and "decodeOF" in js)
    chk("grab matches the clicked colour by default",
        "function findObject(sx,sy,anyColour)" in js and "else if(c[j]!==want) continue;" in js)
    chk("grab's Shift stops at the background", "if(c[j]===bg) continue;" in js)
    chk("grab refuses to select the entire canvas", "===npx()" in js and "whole canvas" in js)
    chk("two-colour mode blocks a third colour",
        "function twoColour()" in js and "function syncMode()" in js)
    chk("importer is capped in two-colour mode", "ic.max=two?2:64" in js)
    chk("tool rail can scroll rather than clip", ".rail::-webkit-scrollbar" in css)
    chk("preview has its own column", ".col.P{" in css and 'class="col P"' in src)
    chk("panel widths are draggable", src.count('class="gut"') == 3 and "setW" in js)
    chk("widths are tokens, so they survive a scale change",
        "--wL:" in css and ".col.L{width:var(--wL)}" in css)
    chk("widths clamp and persist",
        "W_MIN" in js and "W_MAX" in js and "store.set('pf.'+name" in js)
    chk("double-click resets a divider", "dblclick" in js and "W_DEFAULT[name]" in js)
    chk("fifty duotone pairs offered",
        "const DUOTONE=" in js and 'id="duos"' in src and "applyPair" in js
        and js.count("['#") >= 50)
    chk("in-game colour set removed", "OF_PAIRS" not in js)
    chk("swatches show colour only, no captions", "t.textContent=name" not in js)
    chk("picking a pair yields exactly two colours",
        "doc.palette=[{r:0,g:0,b:0,a:0},hexRGB(prim),hexRGB(sec)]" in js)

    # Aseprite's dark accent is gold and blue is reserved for links, which is what
    # keeps the two distinguishable. An earlier revision moved the accent to
    # OpenFront's blue (#2962ff), leaving two near-identical blues doing different
    # jobs. The tool's chrome belongs to the audience that lives in Aseprite;
    # OpenFront fidelity is carried by the format and the preview, not the chrome.
    chk("accent is gold, not OpenFront blue",
        "#2962ff" not in css and "#4b8fff" not in css)

    # States were the part of the system nobody wrote down, so they drifted into
    # inline hex: four `style="color:#e5674b"` strings sat beside a --danger token
    # that already held that job. See docs/09-design-system.md, "States".
    print("\n=== states ===")
    chk("status colour comes from tokens, never inline hex",
        not re.search(r'style="color:#[0-9a-fA-F]', js), )
    chk("focus is an outline in the accent, not a fill",
        "outline:0.1rem solid var(--accent)" in css)
    chk("hover changes fill and border to --edge",
        ".b:hover:not(:disabled){background:var(--edge);border-color:var(--edge)}" in css)
    chk("pressed drops to --well", ".b:active:not(:disabled){background:var(--well)}" in css)
    chk("disabled dims to --well", ".b:disabled{color:var(--well)" in css)
    chk("selected is accent fill with accent ink",
        'background:var(--accent);color:var(--accent-ink)' in css)

    print("\n=== preview & colour input ===")
    chk("preview starts fitted and tiled", "pvScale=0,pvTile=true" in js)
    chk("preview zooms on the wheel", "pvC.parentElement.addEventListener('wheel'" in js)
    chk("fixed 1x/2x/4x steps removed", "data-pv" not in src)
    chk("colour applies without a confirm step",
        "function applyColour" in js and "setC" not in js)
    chk("hex field present and wired", 'id="hex"' in src and "$('hex').addEventListener" in js)
    chk("first paint is guarded (blank-canvas bug)",
        "if(!buf) return;" in js)
    chk("grab backfills with the background", "function liftFill()" in js
        and js.count("liftFill()") >= 3)
    chk("Swap exchanges the colours, so the artwork flips",
        "function swapColours()" in js and "doc.palette[a]=doc.palette[b]" in js)
    chk("export is independent of the selected swatch",
        "function flatIndex(" in js and "flat[i]===2?1:0" in js)
    # A chip click must change what the PENCIL draws, not just what the picker
    # edits. `editSlot` was the bug: it split "active" into two concepts.
    chk("chips make a colour active, so the pencil follows",
        "function setActive(which)" in js
        and "if(which==='b'&&fg!==bg){const t=fg;fg=bg;bg=t;}" in js
        and "$('chipA').onclick=()=>setActive('a')" in js
        and "$('chipB').onclick=()=>setActive('b')" in js)
    chk("editSlot is gone (one concept, not two)", "editSlot" not in js)
    chk("the picker edits the active colour", "doc.palette[fg]=hexRGB(" in js)
    chk("canvas size is stacked and auto-applies",
        '<span class="lb">Width</span>' in src and 'id="resize"' not in src
        and "$('cw').addEventListener('change',applyResize)" in js)
    chk("flex children can shrink", ".r>.b,.duo>.b,.r>select{min-width:0}" in css)

    print("\n=== image import ===")
    chk("import size is stacked number inputs",
        'type="number" id="iw"' in src and 'type="number" id="ih"' in src
        and 'type="range" id="iw"' not in src)
    chk("import size commits on change",
        "$('iw').addEventListener('change'" in js and "$('ih').addEventListener('change'" in js)
    chk("a second image can be chosen",
        'id="iPick"' in src and "$('srcC').onclick" in js
        and "e.target.value=''" in js)
    chk("import can create a new frame",
        'id="iFrame"' in src and "applyConversion('frame')" in js
        and "doc.frames.splice(aFrame+1,0,{cels})" in js)
    chk("all three import modes are distinct",
        all(f"applyConversion('{m}')" in js for m in ("replace", "layer", "frame")))

    print("\n=== stamps ===")
    chk("stamp table present", "const STAMPS=" in js)
    stamps = re.findall(r"\['([a-z]+)','([a-z0-9_-]+)','([A-Za-z0-9_-]+)'\]", js)
    chk("at least 50 stamps ship", len(stamps) >= 50, f"{len(stamps)}")
    # A bare `1fr` is minmax(auto,1fr), and that auto floor is the item's
    # min-content. The stamp buttons hold <canvas> elements whose intrinsic
    # width is the pattern's own width — game/openfront is 66px — so four
    # columns demanded 264px inside a 152px panel. Any grid holding artwork
    # canvases has to pin the track minimum to 0.
    widest = max((decode_stamp_w(d) for _, _, d in stamps), default=0)
    chk("stamp grid tracks cannot be forced open by a wide canvas",
        re.search(r"\.stamps\{[^}]*repeat\(4,minmax\(0,1fr\)\)", css) is not None,
        f"widest stamp is {widest}px")
    chk("stamp buttons and canvases can shrink",
        re.search(r"\.stamps button\{[^}]*min-width:0", css) is not None
        and re.search(r"\.stamps canvas\{[^}]*min-width:0", css) is not None)
    chk("the stamps grid never scrolls sideways",
        re.search(r"\.stamps\{[^}]*overflow-x:hidden", css) is not None)
    chk("no bare 1fr track in a grid that holds canvases",
        "repeat(4,1fr)" not in css.replace(" ", ""))
    chk("stamp names are unique", len({s[1] for s in stamps}) == len(stamps))
    chk("stamps are stored as patternData, not a second format",
        "decodeOF(data)" in js or "decodeOF(s[2])" in js or "decodeOF(d)" in js,
        "stamps reuse the verified codec")
    chk("stamps panel is in the markup", 'id="stamps"' in src and "drawStamps" in js)
    chk("arming is explicit and cancellable",
        "let armed=null" in js and "function disarmStamp()" in js
        and "function placeStamp(" in js)
    chk("Escape disarms", "disarmStamp()" in js and "'Escape'" in js)
    chk("stamps merge rather than replace",
        "// Merge the shape in at the cursor, centred." in js)

    print("\n=== preview zoom ===")
    # The bug: max-width scaled #pvC down exactly as fast as zoom grew it.
    pvc = re.search(r"#pvC\{([^}]*)\}", css)
    chk("#pvC rule found", pvc is not None)
    if pvc:
        chk("no max-width capping the preview canvas", "max-width" not in pvc.group(1),
            pvc.group(1).strip())
    chk("preview centres with margin, not place-items",
        re.search(r"#pvC\{[^}]*margin:auto", css) is not None)
    chk("the preview box scrolls when the canvas outgrows it",
        re.search(r"\.pvbox\{[^}]*overflow:auto", css) is not None)

    print("\n=== desktop seam ===")
    # The same file is the browser build and the Electron renderer. Every native
    # call sits behind native(), so a browser is never asked for pfNative.
    chk("native() is the single feature test",
        "const native=()=>!!(window.pfNative&&window.pfNative.isDesktop);" in js)
    # Whether the browser build ever touches pfNative is a runtime property, so
    # it is asserted in verify-behaviour.js by booting with no pfNative at all.
    # Here we only count the surface, to keep it small and reviewable.
    calls = sorted({c.split(".")[-1] for c in re.findall(r"window\.pfNative\.\w+", js)})
    allowed = {"isDesktop", "saveExport", "openDocument", "saveDocument",
               "readDocument", "onCommand", "setDirty", "setDocumentPath",
               "openExternal"}
    chk("renderer uses only the declared native surface",
        set(calls) <= allowed, f"{calls}")
    chk("exports route through the one download() seam",
        "function download(b,n){" in js and "if(native()){" in js
        and "window.pfNative.saveExport" in js)
    chk("open and autosave share a load path",
        "function loadDocFromJSON(raw)" in js
        and "function restoreDoc(){ return loadDocFromJSON(store.get(SAVE_KEY)); }" in js)
    chk("a command table backs the native menu",
        "const COMMANDS={" in js and "window.__pf={commands:COMMANDS" in js)
    for cmd in ("file.open", "file.save", "file.saveAs", "edit.undo",
                "edit.clear", "view.fit", "help.shortcuts"):
        chk(f"command {cmd!r} exists", f"'{cmd}':" in js)
    # Electron dispatches the accelerator before the page sees the keydown, so
    # handling it in both places runs it twice.
    chk("menu-owned accelerators are not handled twice",
        "const MENU_KEYS=new Set(" in js
        and "if(meta&&native()&&MENU_KEYS.has(e.key.toLowerCase())) return;" in js)
    chk("dirty state is tracked for the close prompt",
        "function markDirty()" in js and "function markClean()" in js
        and "syncStatus();saveSoon();markDirty();" in js)
    chk("external links leave the app window",
        "openExternal" in js and 'a[href^="http"]' in js)

    print("\n=== no third-party content ===")
    # OpenFront's cosmetics.json is CC BY-SA 4.0 and includes characters they
    # cannot sublicense onward, so none of it is redistributed here. These are
    # cheap greps, but they are what stops it drifting back in — see NOTICE.
    chk("no OpenFront-derived stamps", "['game'," not in js)
    chk("their wordmark is not the boot document", "OPENFRONT_WORDMARK" not in js)
    for name in ("grogu", "grogu_head", "openfront_qr", "embelem"):
        chk(f"{name!r} is absent", f"'{name}'" not in js)
    chk("the game-data fixture is not committed",
        not os.path.exists(os.path.join(ROOT, "tests", "fixtures", "patterns.json")))
    chk("the licence-clean corpus is committed",
        os.path.exists(os.path.join(ROOT, "tests", "fixtures", "codec.json")))

    print("\n=== clear ===")
    chk("Clear is a real button, not just a menu item",
        'id="clear"' in src and "$('clear').onclick" in js)
    chk("one implementation behind button, key and menu",
        "function clearArt(all)" in js
        and "clearArt(e.shiftKey)" in js
        and js.count("clearArt(") >= 4)
    chk("clearing is undoable", re.search(r"function clearArt\(all\)\{[\s\S]{0,400}?snap\(\);", js)
        is not None)
    chk("the base layer clears to paper, overlays to transparent",
        "const c=doc.frames[aFrame].cels[li], v=li===0?bg:0;" in js)
    chk("a selection narrows it to that rectangle",
        re.search(r"function clearArt[\s\S]{0,600}?if\(sel\)\{", js) is not None)
    chk("Shift clears every layer", "doc.layers.map((_,i)=>i)" in js)
    chk("Delete and Backspace both work",
        "e.key==='Delete'||e.key==='Backspace'" in js)
    chk("the old transparent-fill clear is gone", "cel().fill(0)" not in js)

    print("\n=== storage safety ===")
    # This is what made the published artifact render blank: `localStorage` does
    # not return null in a sandboxed iframe, it THROWS on property access, and
    # an unguarded read at module scope killed the boot IIFE before first paint.
    # The invariant is narrow and easy to check: the identifier appears only
    # inside the `store` helper, which wraps every call in try/catch.
    store_decl = re.search(r"const store=\{.*?\}\};", js, re.S)
    chk("a guarded storage helper exists", store_decl is not None)
    if store_decl:
        outside = js.replace(store_decl.group(0), "")
        outside = re.sub(r"//[^\n]*", "", outside)   # comments may name it freely
        hits = re.findall(r"\blocalStorage\b", outside)
        chk("no localStorage access outside the helper", not hits,
            f"{len(hits)} unguarded reference(s)")
        for m in ("get(k)", "set(k,v)", "del(k)"):
            chk(f"store.{m.split('(')[0]} is wrapped in try/catch",
                m in store_decl.group(0)
                and store_decl.group(0).count("try{") >= 3)
        chk("store.set reports whether the write landed",
            "return true;}catch{return false;}" in store_decl.group(0))
    chk("the scale read at module scope is guarded", "localStorage.getItem('pf.ui')" not in js)

    print("\n=== autosave ===")
    chk("document is serialised, not just preferences",
        "function serialiseDoc()" in js and "function restoreDoc()" in js
        and "SAVE_KEY='pf.doc'" in js)
    chk("cel bytes survive the round trip",
        "const b64enc=" in js and "const b64dec=" in js)
    chk("saves are debounced", "function saveSoon()" in js and "800" in js)
    chk("every commit schedules a save", "syncStatus();saveSoon();" in js)
    chk("quota is guarded, and it gives up rather than throwing per stroke",
        "SAVE_MAX" in js and "saveDead=true" in js and "payload.length>SAVE_MAX" in js)
    chk("a corrupt payload falls back to a fresh document",
        "if(d.v!==1||!d.frames?.length) return false;" in js)
    chk("restore is announced with a way out",
        "toast('Restored your last pattern','Start fresh',startFresh)" in js
        and "function startFresh()" in js)
    chk("Start fresh clears the save and the history",
        "store.del(SAVE_KEY)" in js
        and "past.length=0;future.length=0;" in js)
    chk("an action toast takes clicks; a plain one cannot",
        ".toast.act{pointer-events:auto}" in css
        and "t.classList.toggle('act',!!action)" in js)

    print("\n=== load an existing pattern ===")
    chk("load row present", 'id="ofIn"' in src and 'id="ofLoad"' in src)
    chk("load has its own status line, so refreshOF cannot clobber it",
        'id="ofLoadStat"' in src and "function loadStat(" in js)
    for msg in ("Not base64url", "the format allows", "exceeds the"):
        chk(f"specific message: {msg!r}", msg in js)
    chk("decode errors are distinct, not generic",
        all(m in js for m in ("'too short'", "'unsupported version '", "'payload truncated'")))
    chk("load is undoable", re.search(r"\$\('ofLoad'\)\.onclick[\s\S]{0,900}?snap\(\);", js)
        is not None)
    chk("load fits the result to the window",
        re.search(r"\$\('ofLoad'\)\.onclick[\s\S]{0,1400}?fullSync\(\);fitCanvas\(\);", js)
        is not None)

    print("\n=== fit to window ===")
    chk("Fit button present", 'id="fit"' in src and "function fitCanvas()" in js)
    chk("fit accounts for the interface scale", "doc.w*uiScale" in js and "doc.h*uiScale" in js)
    chk("fit subtracts the stage padding", "paddingLeft" in js)
    chk("fit clamps to the zoom slider's range",
        "Math.max(1,Math.min(48,z||1))" in js)
    chk("Shift+0 fits", "fitCanvas" in js and "'0'" in js)
    chk("boot fits after layout settles", "requestAnimationFrame(fitCanvas)" in js)

    print("\n=== shortcut overlay ===")
    chk("overlay markup present", 'id="ovHelp"' in src and 'id="helpBody"' in src)
    chk("shortcut table is data, not hand-written HTML", "const HELP=" in js)
    chk("all five groups covered",
        all(g in js for g in ("'Tools'", "'Colour'", "'View'", "'Edit'", "'Frames'")))
    chk("? toggles it", "function toggleHelp()" in js and "'?'" in js)
    chk("Escape closes it", "ovHelp" in js and "'Escape'" in js)

    print()
    if fails:
        print(f"*** {len(fails)} FAILURE(S) ***")
        for f in fails:
            print(f"    - {f}")
        return 1
    print("ALL UI CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
