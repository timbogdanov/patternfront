#!/usr/bin/env node
/*
 * Run the editor's REAL functions outside the browser.
 *
 * verify-ui.py checks that the source says the right things. This checks that
 * the code does the right things: it lifts the actual function bodies out of
 * app/patternfront.html by name, drops them into a sandbox with the smallest
 * stubs that will hold them up, and exercises them.
 *
 * Nothing here is a reimplementation. If a function changes, this runs the
 * changed version — that is the whole point.
 *
 *   node tools/verify-behaviour.js
 */

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP = path.join(__dirname, '..', 'app', 'patternfront.html');
const src = fs.readFileSync(APP, 'utf8');
const js = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

let failures = 0;
function chk(name, ok, detail) {
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures++;
}

/* ── source extraction ─────────────────────────────────────────────────── */

// Scan forward from `open` to its matching close, skipping strings, template
// literals and comments well enough for this file.
//
// The backslash case matters: in `.replace(/\//g,'_')` the escaped slash and
// the regex's closing delimiter sit next to each other, and a naive scanner
// reads that `//` as a line comment and eats the rest of the line — including,
// in encodeOF, the closing brace. Skipping the character after a backslash
// costs nothing and removes the whole class of problem.
function matchBrace(text, from, open = '{', close = '}') {
  let depth = 0;
  for (let i = from; i < text.length; i++) {
    const c = text[i];
    if (c === '\\') { i++; continue; }
    if (c === '/' && text[i + 1] === '/') { i = text.indexOf('\n', i); if (i < 0) break; continue; }
    if (c === '/' && text[i + 1] === '*') { i = text.indexOf('*/', i) + 1; continue; }
    if (c === "'" || c === '"' || c === '`') {
      const q = c;
      for (i++; i < text.length; i++) {
        if (text[i] === '\\') { i++; continue; }
        if (text[i] === q) break;
      }
      continue;
    }
    if (c === open) depth++;
    else if (c === close) { depth--; if (depth === 0) return i; }
  }
  throw new Error('unbalanced from ' + from);
}

function grabFunction(name) {
  const at = js.indexOf(`function ${name}(`);
  if (at < 0) throw new Error(`function ${name} not found`);
  const brace = js.indexOf('{', js.indexOf(')', at));
  return js.slice(at, matchBrace(js, brace) + 1);
}

// `const NAME=...;` or `let NAME=...;` up to the terminating semicolon at depth 0.
function grabConst(name) {
  const m = new RegExp(`\\b(?:const|let)\\s+${name}\\s*=`).exec(js);
  if (!m) throw new Error(`binding ${name} not found`);
  let i = m.index + m[0].length, depth = 0;
  for (; i < js.length; i++) {
    const c = js[i];
    if (c === '\\') { i++; continue; }
    if (c === "'" || c === '"' || c === '`') {
      const q = c;
      for (i++; i < js.length; i++) { if (js[i] === '\\') { i++; continue; } if (js[i] === q) break; }
      continue;
    }
    if ('([{'.includes(c)) depth++;
    else if (')]}'.includes(c)) depth--;
    else if (c === ';' && depth === 0) break;
  }
  return js.slice(m.index, i + 1);
}

// The body of an arrow handler assigned to $('id').onclick, as a callable.
function grabHandler(id) {
  const key = `$('${id}').onclick=`;
  const at = js.indexOf(key);
  if (at < 0) throw new Error(`handler for ${id} not found`);
  const brace = js.indexOf('{', at);
  const body = js.slice(brace + 1, matchBrace(js, brace));
  return body;
}

/* ── sandbox ───────────────────────────────────────────────────────────── */

function makeStore() {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: k => { m.delete(k); },
    _map: m,
  };
}

function sandbox(extra = {}) {
  const toasts = [];
  const ctx = {
    console, setTimeout, clearTimeout, Uint8Array, Math, JSON, Error, RegExp,
    btoa: s => Buffer.from(s, 'binary').toString('base64'),
    atob: s => Buffer.from(s, 'base64').toString('binary'),
    localStorage: makeStore(),
    toast: (m, a) => toasts.push(m),
    _toasts: toasts,
    ...extra,
  };
  vm.createContext(ctx);
  return ctx;
}

function run(ctx, code) {
  try { vm.runInContext(code, ctx); }
  catch (e) {
    if (process.env.PF_DUMP) fs.writeFileSync(process.env.PF_DUMP, code);
    throw e;
  }
}

/* ── 0. storage in a hostile context ───────────────────────────────────── */
//
// This is the bug that made the published artifact render blank. In a sandboxed
// iframe `localStorage` does not return null — touching the property throws a
// SecurityError. The editor read it at module scope, so the boot IIFE died
// before first paint: stylesheet applied, title showed, nothing rendered.
//
// The whole suite below would have passed throughout, because a normal sandbox
// has working storage. So this test builds a hostile one on purpose.

console.log('=== storage in a hostile context ===');
{
  const hostile = () => {
    const ctx = { console, JSON, Error };
    Object.defineProperty(ctx, 'localStorage', {
      get() { throw new Error('SecurityError: Access is denied for this document'); },
    });
    vm.createContext(ctx);
    return ctx;
  };

  const ctx = hostile();
  let threw = null;
  try {
    run(ctx, [
      grabConst('store'),
      "globalThis._r=store.get('pf.ui');",
      "globalThis._w=store.set('pf.ui','2');",
      "store.del('pf.ui');",
      "globalThis._scale=+(store.get('pf.ui')||1.5);",
    ].join('\n'));
  } catch (e) { threw = e.message; }

  chk('reading storage that throws does not propagate', threw === null, threw || '');
  chk('a failed read reads as absent', ctx._r === null);
  chk('a failed write reports false', ctx._w === false);
  chk('the interface scale falls back to its default', ctx._scale === 1.5, String(ctx._scale));

  // And the specific line that broke it: the module-scope read must be guarded.
  chk('the module-scope scale read goes through the helper',
      /let uiScale=\+\(store\.get\('pf\.ui'\)\|\|1\.5\);/.test(js));
  chk('loadWidths reads through the helper too',
      /parseFloat\(store\.get\('pf\.'\+k\)\)/.test(js));

  // A working store still behaves.
  const okCtx = sandbox();
  run(okCtx, [grabConst('store'),
    "globalThis._a=store.set('k','v'); globalThis._b=store.get('k');",
    "store.del('k'); globalThis._c=store.get('k');"].join('\n'));
  chk('a working store round-trips', okCtx._a === true && okCtx._b === 'v' && okCtx._c === null);
}

/* ── 1. autosave round-trip ────────────────────────────────────────────── */

console.log('=== autosave ===');
{
  const ctx = sandbox();
  run(ctx, [
    grabConst('store'), grabConst('SAVE_KEY'), grabConst('saveTimer'),
    grabConst('b64enc'), grabConst('b64dec'),
    grabFunction('serialiseDoc'), grabFunction('loadDocFromJSON'),
    grabFunction('restoreDoc'),
    grabFunction('saveSoon'),
    'var doc=null;',
  ].join('\n'));

  // A deliberately awkward document: three layers, four frames, a null cel
  // (an empty layer on one frame), a non-integer opacity, a locked layer.
  const W = 37, H = 23, N = W * H;
  const mk = seed => {
    const a = new Uint8Array(N);
    for (let i = 0; i < N; i++) a[i] = (i * seed + (seed >> 2)) & 0xff;
    return Array.from(a);
  };
  const original = {
    w: W, h: H,
    palette: [{ r: 0, g: 0, b: 0, a: 0 }, { r: 255, g: 255, b: 255, a: 255 },
              { r: 18, g: 200, b: 7, a: 255 }],
    layers: [{ name: 'Base', visible: true, locked: false, opacity: 1 },
             { name: 'Ink', visible: false, locked: true, opacity: 0.37 },
             { name: 'Top', visible: true, locked: false, opacity: 0.5 }],
    frames: [0, 1, 2, 3].map(f => ({
      cels: [0, 1, 2].map(l => (f === 2 && l === 1 ? null : mk(f * 3 + l + 1))),
    })),
  };
  run(ctx, `doc=${JSON.stringify(original)};
    for(const f of doc.frames) f.cels=f.cels.map(c=>c?Uint8Array.from(c):null);`);

  run(ctx, `globalThis._payload=serialiseDoc();
    localStorage.setItem(SAVE_KEY,_payload);
    doc=null; globalThis._ok=restoreDoc();`);

  chk('restoreDoc reports success', ctx._ok === true);

  const back = vm.runInContext(`JSON.stringify({w:doc.w,h:doc.h,
    palette:doc.palette,layers:doc.layers,
    frames:doc.frames.map(f=>f.cels.map(c=>c?Array.from(c):null))})`, ctx);
  const got = JSON.parse(back);
  chk('dimensions survive', got.w === W && got.h === H);
  chk('palette survives', JSON.stringify(got.palette) === JSON.stringify(original.palette));
  chk('layer flags and opacity survive',
      JSON.stringify(got.layers) === JSON.stringify(original.layers));
  const want = original.frames.map(f => f.cels);
  chk('every cel byte matches', JSON.stringify(got.frames) === JSON.stringify(want),
      `${want.flat().filter(Boolean).length} cels, ${N} px each`);
  chk('an empty layer stays empty (null, not zero-filled)',
      got.frames[2][1] === null);

  // A garbage payload must not throw, and must not half-load a document.
  run(ctx, `localStorage.setItem(SAVE_KEY,'{not json'); globalThis._g1=restoreDoc();
            localStorage.setItem(SAVE_KEY,'{"v":9}');  globalThis._g2=restoreDoc();
            localStorage.setItem(SAVE_KEY,'{"v":1,"frames":[]}'); globalThis._g3=restoreDoc();`);
  chk('corrupt JSON is refused, not thrown', ctx._g1 === false);
  chk('a future version is refused', ctx._g2 === false);
  chk('a frameless document is refused', ctx._g3 === false);
}

/* ── 2. autosave gives up past quota rather than throwing per stroke ───── */

const oversize = new Promise(resolve => {
  const ctx = sandbox();
  run(ctx, [
    // one statement declares SAVE_KEY and SAVE_MAX; another, saveTimer and saveDead
    grabConst('store'), grabConst('SAVE_KEY'), grabConst('saveTimer'),
    grabConst('b64enc'), grabConst('b64dec'),
    grabFunction('serialiseDoc'), grabFunction('saveSoon'),
    'var doc=null;',
  ].join('\n'));

  // 129x65 is the format's maximum; 220 frames of it clears 2 MB of base64.
  run(ctx, `const N=129*65;
    doc={w:129,h:65,palette:[{r:0,g:0,b:0,a:0}],
      layers:[{name:'L',visible:true,locked:false,opacity:1}],
      frames:Array.from({length:220},()=>({cels:[new Uint8Array(N).fill(2)]}))};
    globalThis._len=serialiseDoc().length;
    saveSoon();`);

  chk('the test document really is oversized',
      ctx._len > 2 * 1024 * 1024, `${(ctx._len / 1048576).toFixed(2)} MB`);

  // `let saveDead` is a lexical binding, not a property of the sandbox object,
  // so it has to be read by evaluating the name inside the context.
  const peek = expr => vm.runInContext(expr, ctx);
  setTimeout(() => {
    chk('oversized documents stop autosaving', peek('saveDead') === true);
    chk('nothing was written', ctx.localStorage.getItem(peek('SAVE_KEY')) === null);
    chk('the user is told once', ctx._toasts.length === 1, JSON.stringify(ctx._toasts));

    // Second attempt: still silent, no second toast, no throw.
    run(ctx, 'saveSoon();');
    setTimeout(() => {
      chk('it does not nag on every subsequent stroke', ctx._toasts.length === 1);
      resolve();
    }, 900);
  }, 900);
});

/* ── 3. the colour bug: a chip click must change what the pencil draws ──── */

function colourTests() {
  console.log('\n=== colour follows selection ===');
  const ctx = sandbox({ syncColour: () => {} });
  run(ctx, `var fg=2,bg=1;\n${grabFunction('setActive')}`);

  run(ctx, `setActive('b');`);
  chk('clicking chip B makes the secondary colour active',
      ctx.fg === 1 && ctx.bg === 2, `fg=${ctx.fg} bg=${ctx.bg}`);

  run(ctx, `setActive('a');`);
  chk('clicking chip A leaves it alone (A is always the active slot)',
      ctx.fg === 1 && ctx.bg === 2, `fg=${ctx.fg} bg=${ctx.bg}`);

  run(ctx, `setActive('b');`);
  chk('clicking B again swaps back', ctx.fg === 2 && ctx.bg === 1);

  run(ctx, `fg=5;bg=5;setActive('b');`);
  chk('a no-op swap stays a no-op', ctx.fg === 5 && ctx.bg === 5);

  // And the value the pencil actually paints with is fg — this is the half I
  // got wrong last time, so it gets asserted against the source directly.
  chk('the stroke value is fg', /\n\s*sv=fg;/.test(js));
  chk('fill, line and shapes use the same sv', /bucket\(p\.x,p\.y,sv\)/.test(js));
  chk('nothing reads a separate edit slot', !/editSlot/.test(js));
}

/* ── 4. load rejects bad input, each with its own message ──────────────── */

function loadTests() {
  console.log('\n=== load an existing pattern ===');
  const handler = grabHandler('ofLoad');
  const ctx = sandbox({
    snap: () => {}, fullSync: () => {}, fitCanvas: () => {},
    hexRGB: h => ({ r: 0, g: 0, b: 0, a: 255, h }),
  });
  run(ctx, [
    grabConst('OF_MAXW'), grabFunction('encodeOF'), grabFunction('decodeOF'),
    grabConst('PRESETS'),
    'var doc=null,aLayer=0,aFrame=0,fg=0,bg=0,sel=null,_field="",_stat="";',
    "var $=id=>({get value(){return _field;},set value(v){_field=v;},"
      + 'set innerHTML(v){_stat=v;},set textContent(v){_stat=v;}});',
    grabFunction('loadStat'),
    `function load(s){_field=s;_stat='';(function(){${handler}})();return _stat;}`,
  ].join('\n'));

  const cases = [
    ['', 'Paste a patternData', 'empty input'],
    ['not base64!!', 'Not base64url', 'illegal characters'],
    ['A'.repeat(1500), 'the format allows', 'over the 1403-char limit'],
    // version byte 1 instead of 0
    [Buffer.from([1, 0, 0, 0]).toString('base64url'), 'unsupported version 1', 'wrong version'],
    // header says 129x65 but carries one byte of payload
    [Buffer.from([0, 0xf8, 0xff, 0x00]).toString('base64url'), 'truncated', 'truncated payload'],
    [Buffer.from([0, 0]).toString('base64url'), 'too short', 'shorter than a header'],
  ];
  for (const [input, want, label] of cases) {
    const out = load(ctx, input);
    chk(`rejects ${label}`, out.includes(want) && out.includes('--danger'),
        JSON.stringify(out.replace(/<[^>]*>/g, '')));
  }

  // ...and a real pattern loads, with the bit->index mapping the exporter expects.
  const good = vm.runInContext(
    'encodeOF(6,4,3,[1,0,1,0,1,0, 0,1,0,1,0,1, 1,1,0,0,1,1, 0,0,1,1,0,0])', ctx);
  const out = load(ctx, good);
  chk('a valid pattern loads', out.includes('Loaded 6×4, scale 3'), JSON.stringify(out));
  const shape = vm.runInContext(
    'JSON.stringify({w:doc.w,h:doc.h,pal:doc.palette.length,'
    + 'cel:Array.from(doc.frames[0].cels[0])})', ctx);
  const d = JSON.parse(shape);
  chk('loaded document is 6x4 with a two-colour palette', d.w === 6 && d.h === 4 && d.pal === 3);
  // bit 0 is the PRIMARY slot -> index 1; bit 1 -> index 2.
  chk('bit 0 maps to the primary slot (index 1)',
      JSON.stringify(d.cel) === JSON.stringify(
        [1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0]
          .map(b => (b ? 2 : 1))));
  chk('the active colour is the primary slot', ctx.fg === 2 && ctx.bg === 1);
}

function load(ctx, s) {
  return vm.runInContext(`load(${JSON.stringify(s)})`, ctx);
}

/* ── 5. preview zoom is real geometry, not just a readout ──────────────── */

function previewTests() {
  console.log('\n=== preview zoom ===');
  const css = [...src.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('');
  const rule = /#pvC\{([^}]*)\}/.exec(css);
  chk('#pvC has no max-width', rule && !/max-width/.test(rule[1]),
      rule ? rule[1].trim() : 'rule missing');
  chk('#pvC has no width/height override that would cap it',
      rule && !/(^|;)\s*(width|height):/.test(rule[1]));

  // The readout used to climb while the image stood still. Run the real
  // drawPreview at a ladder of zoom levels and measure the canvas it produces.
  const W = 24, H = 16;
  const measure = (pvScale, pvTile) => {
    const ctx = sandbox({
      ImageData: class { constructor(w, h) { this.data = { set() {} }; } },
      document: { createElement: () => ({ width: 0, height: 0, getContext: () => stubCtx() }) },
      pvC: { width: 0, height: 0 },
      pvG: stubCtx(),
      pvFitScale: () => 3,
      $: () => null,
    });
    run(ctx, [
      `var doc={w:${W},h:${H}},buf=new Uint8Array(${W * H * 4});`,
      `var pvScale=${pvScale},pvTile=${pvTile};`,
      grabFunction('pvEff'), grabFunction('drawPreview'), 'drawPreview();',
    ].join('\n'));
    return { w: ctx.pvC.width, h: ctx.pvC.height };
  };

  const ladder = [1, 2, 4, 8, 16, 32, 64].map(s => measure(s, false));
  chk('canvas pixel size tracks the zoom exactly',
      ladder.every((r, i) => r.w === W * [1, 2, 4, 8, 16, 32, 64][i]
                          && r.h === H * [1, 2, 4, 8, 16, 32, 64][i]),
      ladder.map(r => `${r.w}x${r.h}`).join(' '));
  chk('it keeps growing past the fit point (the reported bug)',
      ladder.every((r, i) => i === 0 || r.w > ladder[i - 1].w));

  const fit = measure(0, false);
  chk('zoom 0 means "fit", and uses the fitted scale',
      fit.w === W * 3 && fit.h === H * 3, `${fit.w}x${fit.h}`);

  const tiled = measure(4, true);
  chk('tiling renders a 3x3 block at the same zoom',
      tiled.w === W * 4 * 3 && tiled.h === H * 4 * 3, `${tiled.w}x${tiled.h}`);
}

function stubCtx() {
  const noop = () => {};
  return new Proxy({}, {
    get: (_, k) => (k === 'canvas' ? { width: 0, height: 0 } : noop),
    set: () => true,
  });
}

/* ── 6. fit sizes the artwork to the stage, at any interface scale ─────── */

function fitTests() {
  console.log('\n=== fit to window ===');
  const results = [];
  for (const [boxW, boxH, dw, dh, ui] of [
    [1200, 800, 129, 65, 1], [1200, 800, 129, 65, 1.5],
    [400, 400, 32, 32, 1.5], [40, 40, 129, 65, 3], [1200, 800, 8, 8, 1],
  ]) {
    const ctx = sandbox({
      layout: () => {},
      getComputedStyle: () => ({ paddingLeft: '8px' }),
    });
    run(ctx, [
      `var doc={w:${dw},h:${dh}},uiScale=${ui},zoom=1;`,
      `var $=id=>id==='scroll'?{clientWidth:${boxW},clientHeight:${boxH}}:{value:0,textContent:0};`,
      grabFunction('fitCanvas'),
      'fitCanvas();',
    ].join('\n'));
    results.push({ boxW, boxH, dw, dh, ui, zoom: ctx.zoom });
  }
  for (const r of results) {
    const shown = { w: r.dw * r.zoom * r.ui, h: r.dh * r.zoom * r.ui };
    const fits = shown.w <= r.boxW && shown.h <= r.boxH;
    const inRange = r.zoom >= 1 && r.zoom <= 48 && Number.isInteger(r.zoom);
    // A tiny stage can't fit a big pattern at zoom 1 — clamping to 1 is right.
    const tooSmall = r.dw * r.ui > r.boxW || r.dh * r.ui > r.boxH;
    chk(`${r.dw}x${r.dh} in ${r.boxW}x${r.boxH} @${r.ui}x -> zoom ${r.zoom}`,
        inRange && (fits || (tooSmall && r.zoom === 1)),
        `displays ${Math.round(shown.w)}x${Math.round(shown.h)}`);
  }

  // Doubling the interface scale must halve the zoom — displayed size is the
  // product of the two, and this is exactly where the old code went wrong.
  const z = {};
  for (const ui of [1, 2]) {
    const ctx = sandbox({ layout: () => {}, getComputedStyle: () => ({ paddingLeft: '0px' }) });
    run(ctx, [
      `var doc={w:20,h:20},uiScale=${ui},zoom=1;`,
      "var $=id=>id==='scroll'?{clientWidth:800,clientHeight:800}:{value:0,textContent:0};",
      grabFunction('fitCanvas'), 'fitCanvas();',
    ].join('\n'));
    z[ui] = ctx.zoom;
  }
  chk('zoom halves when the interface scale doubles',
      z[1] === 40 && z[2] === 20, `1x->${z[1]}, 2x->${z[2]}`);
}

/* ── 7. grab: 8-connected flood fill over an ASCII scene ───────────────── */

function grabTests() {
  console.log('\n=== grab a shape ===');

  // '.' background (index 1), digits are colour indices, ' ' is transparent (0).
  const SCENE = [
    '1111111111',
    '1223311111',
    '1223311111',
    '1111111111',
    '1114111111',
    '1111411111',   // 4s touch only at the corners — 8-connected, so one object
    '1114111111',
    '1111111111',
    '1111155111',
    '1111155111',
  ];
  const W = SCENE[0].length, H = SCENE.length;
  const flat = SCENE.join('').split('').map(Number);

  const make = (wrap) => {
    const ctx = sandbox();
    run(ctx, [
      `var doc={w:${W},h:${H}},wrapDraw=${wrap},bg=1;`,
      `var _cel=Uint8Array.from(${JSON.stringify(flat)});`,
      'function cel(){return _cel;} function npx(){return doc.w*doc.h;}',
      'function inside(x,y){return x>=0&&y>=0&&x<doc.w&&y<doc.h;}',
      'function mod(a,n){return ((a%n)+n)%n;}',
      grabFunction('findObject'),
      'function count(x,y,any){const m=findObject(x,y,any);'
        + 'return m?m.reduce((a,b)=>a+b,0):null;}',
    ].join('\n'));
    return expr => vm.runInContext(expr, ctx);
  };

  const q = make(false);
  const cases = [
    ['a 2x2 block of 2s', 'count(1,1,false)', 4],
    ['the adjacent 3s are a separate object', 'count(3,1,false)', 4],
    ['Shift merges the touching 2s and 3s', 'count(1,1,true)', 8],
    ['diagonal-only contact still connects (8-connected)', 'count(3,4,false)', 3],
    ['a 2x2 block near the edge', 'count(5,8,false)', 4],
    ['clicking the background selects the background', 'count(0,0,false)', 100 - 4 - 4 - 3 - 4],
    ['clicking outside the canvas returns nothing', 'count(-1,0,false)', null],
    ['clicking past the right edge returns nothing', `count(${W},0,false)`, null],
    ['clicking past the bottom returns nothing', `count(0,${H},false)`, null],
    ['Shift from a shape stops at the background', 'count(3,4,true)', 3],
    // Shift refuses to WALK THROUGH the background, so seeding on it picks up
    // the seed plus whatever non-background it directly touches — here the
    // 2/3 block diagonally adjacent to (0,0). It cannot run away across the
    // paper, which is the property that matters.
    ['Shift cannot traverse the background', 'count(0,0,true)', 1 + 8],
  ];
  for (const [label, expr, want] of cases) {
    const got = q(expr);
    chk(label, got === want, `${expr} -> ${got}${got === want ? '' : ` (want ${want})`}`);
  }

  // Wrap mode joins shapes across the seam.
  const wrapScene = ['5111115', '5111115'];
  const ctxW = sandbox();
  run(ctxW, [
    'var doc={w:7,h:2},wrapDraw=true,bg=1;',
    `var _cel=Uint8Array.from(${JSON.stringify(wrapScene.join('').split('').map(Number))});`,
    'function cel(){return _cel;} function npx(){return doc.w*doc.h;}',
    'function inside(x,y){return x>=0&&y>=0&&x<doc.w&&y<doc.h;}',
    'function mod(a,n){return ((a%n)+n)%n;}',
    grabFunction('findObject'),
    'globalThis._n=findObject(0,0,false).reduce((a,b)=>a+b,0);',
  ].join('\n'));
  chk('wrap joins a shape across the seam', ctxW._n === 4, `${ctxW._n} px`);

  const ctxN = sandbox();
  run(ctxN, [
    'var doc={w:7,h:2},wrapDraw=false,bg=1;',
    `var _cel=Uint8Array.from(${JSON.stringify(wrapScene.join('').split('').map(Number))});`,
    'function cel(){return _cel;} function npx(){return doc.w*doc.h;}',
    'function inside(x,y){return x>=0&&y>=0&&x<doc.w&&y<doc.h;}',
    'function mod(a,n){return ((a%n)+n)%n;}',
    grabFunction('findObject'),
    'globalThis._n=findObject(0,0,false).reduce((a,b)=>a+b,0);',
  ].join('\n'));
  chk('without wrap the two halves stay separate', ctxN._n === 2, `${ctxN._n} px`);
}

/* ── 8. clear ──────────────────────────────────────────────────────────── */

function clearTests() {
  console.log('\n=== clear ===');
  const W = 6, H = 4, N = W * H;

  const setup = (layers, selection) => {
    const ctx = sandbox({ commit: () => {}, snap: () => {} });
    run(ctx, [
      `var doc={w:${W},h:${H},layers:${JSON.stringify(
        Array.from({ length: layers }, (_, i) => ({ name: 'L' + i })))},`,
      `  frames:[{cels:${JSON.stringify(
        Array.from({ length: layers }, () => Array(N).fill(2)))}}]};`,
      'doc.frames[0].cels=doc.frames[0].cels.map(c=>Uint8Array.from(c));',
      `var aFrame=0,aLayer=0,bg=1,sel=${selection ? JSON.stringify(selection) : 'null'};`,
      grabFunction('clearArt'),
    ].join('\n'));
    return ctx;
  };
  const cel = (ctx, i) =>
    JSON.parse(vm.runInContext(`JSON.stringify(Array.from(doc.frames[0].cels[${i}]))`, ctx));

  let ctx = setup(1, null);
  run(ctx, 'clearArt(false);');
  chk('clearing the base layer fills it with paper, not holes',
      cel(ctx, 0).every(v => v === 1), cel(ctx, 0).slice(0, 6).join(''));
  chk('it says so', ctx._toasts.length === 1 && /Cleared the canvas/.test(ctx._toasts[0]),
      JSON.stringify(ctx._toasts));

  ctx = setup(3, null);
  run(ctx, 'aLayer=2;clearArt(false);');
  chk('clearing an overlay leaves transparency, not an opaque sheet',
      cel(ctx, 2).every(v => v === 0));
  chk('other layers are untouched',
      cel(ctx, 0).every(v => v === 2) && cel(ctx, 1).every(v => v === 2));

  ctx = setup(3, null);
  run(ctx, 'clearArt(true);');
  chk('Shift clears every layer at once',
      cel(ctx, 0).every(v => v === 1)
      && cel(ctx, 1).every(v => v === 0)
      && cel(ctx, 2).every(v => v === 0));

  // A selection confines it: 2x2 at (1,1) on a 6x4 sheet.
  ctx = setup(1, { x: 1, y: 1, w: 2, h: 2 });
  run(ctx, 'clearArt(false);');
  const got = cel(ctx, 0);
  const inside = [1 * W + 1, 1 * W + 2, 2 * W + 1, 2 * W + 2];
  chk('a selection confines the clear to its rectangle',
      inside.every(i => got[i] === 1)
      && got.every((v, i) => inside.includes(i) || v === 2),
      got.join(''));

  // Undo must be able to bring it back, so snap() has to run first — and only
  // when there is actually something to clear.
  const snapCtx = sandbox({ commit: () => {} });
  run(snapCtx, [
    `var doc={w:${W},h:${H},layers:[{name:'L0'}],frames:[{cels:[null]}]};`,
    'var aFrame=0,aLayer=0,bg=1,sel=null,snaps=0;',
    'function snap(){snaps++;}',
    grabFunction('clearArt'),
    'clearArt(false);',
  ].join('\n'));
  chk('an empty cel is a no-op, with no undo entry',
      vm.runInContext('snaps', snapCtx) === 0);
}

/* ── run ───────────────────────────────────────────────────────────────── */

oversize.then(async () => {
  colourTests();
  loadTests();
  previewTests();
  fitTests();
  grabTests();
  clearTests();
  console.log();
  if (failures) {
    console.log(`*** ${failures} FAILURE(S) ***`);
    process.exit(1);
  }
  console.log('ALL BEHAVIOUR CHECKS PASSED');
});
