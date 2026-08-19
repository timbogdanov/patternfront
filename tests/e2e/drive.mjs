#!/usr/bin/env node
/*
 * Drive the real app the way a person does.
 *
 * WHY THIS EXISTS
 * ---------------
 * The rest of the suite is strong on pure functions — codec, sampler, document
 * layer — and CI already launches the app and asserts it booted. Nothing drew a
 * stroke, saved a file, reopened it and checked the result. The gap is not
 * hypothetical: v0.1.0 shipped a macOS build that could not be opened at all,
 * because every check ran against a build nobody had downloaded.
 *
 * So this drives the actual window: real mouse input through the browser's own
 * event pipeline, the real native save path, the real document round-trip.
 *
 *   node tests/e2e/drive.mjs                 # the repo, via the local electron
 *   node tests/e2e/drive.mjs --app <binary>  # a packaged .app / .exe
 *
 * Headless Linux needs a display: `xvfb-run --auto-servernum node tests/e2e/drive.mjs`.
 * Exits 2 — "could not run", not "found a problem" — when electron or a display
 * is missing, so tools/verify-all.sh reports it as a skip rather than a failure.
 *
 * Two things this had to get right, both of which cost real time to find:
 *
 *   * The renderer's CSP has no 'unsafe-eval', so every evaluate() must be given
 *     a function. Passing a string makes Playwright eval it, and the page blocks
 *     it — the failure reads as a mysterious undefined rather than a CSP error.
 *   * The canvas calls setPointerCapture(), which throws on a synthetic
 *     PointerEvent. Drawing has to go through page.mouse, which is real input as
 *     far as the page is concerned.
 */

import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..', '..');

const argApp = process.argv.indexOf('--app');
const APP = argApp > 0 ? process.argv[argApp + 1] : null;

const localElectron = process.platform === 'darwin'
  ? path.join(ROOT, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
  : process.platform === 'win32'
    ? path.join(ROOT, 'node_modules/electron/dist/electron.exe')
    : path.join(ROOT, 'node_modules/electron/dist/electron');

const executablePath = APP || localElectron;
if (!existsSync(executablePath)) {
  console.log(`electron not found at ${executablePath}`);
  console.log('run: npm ci');
  process.exit(2);
}
if (process.platform === 'linux' && !process.env.DISPLAY) {
  console.log('no DISPLAY — run under xvfb-run');
  process.exit(2);
}

let electron;
try {
  ({ _electron: electron } = await import('playwright-core'));
} catch {
  console.log('playwright-core is not installed');
  console.log('run: npm ci');
  process.exit(2);
}

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail });
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
};

const SHOTS = process.env.SCREENSHOT_DIR || path.join(tmpdir(), 'pf-e2e');
mkdirSync(SHOTS, { recursive: true });
const savePath = path.join(mkdtempSync(path.join(tmpdir(), 'pf-')), 'round-trip.patternfront');

// A profile of its own, so this never fights the single-instance lock held by a
// copy the developer happens to be using.
const profile = mkdtempSync(path.join(tmpdir(), 'pf-profile-'));
const args = [`--user-data-dir=${profile}`];
if (!APP) args.unshift(ROOT);
if (process.platform === 'linux' && process.env.PF_NO_SANDBOX) args.push('--no-sandbox');

const app = await electron.launch({ executablePath, args, timeout: 60_000 });
const errors = [];
let page;

const state = () => page.evaluate(() => window.__pfState());
const title = () => app.evaluate(({ BrowserWindow }) =>
  BrowserWindow.getAllWindows()[0].getTitle());
const cmd = (id, arg) => app.evaluate(({ BrowserWindow }, a) =>
  BrowserWindow.getAllWindows()[0].webContents.send('command', a.id, a.arg), { id, arg });
const colours = (canvasId) => page.evaluate((cid) => {
  const c = document.getElementById(cid);
  const d = c.getContext('2d', { willReadFrequently: true })
             .getImageData(0, 0, c.width, c.height).data;
  const seen = new Set();
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200) seen.add(`${d[i]},${d[i+1]},${d[i+2]}`);
  return [...seen].sort();
}, canvasId);

try {
  page = await app.firstWindow();
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(e.message));
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(() => !!window.__pfState, null, { timeout: 20_000 });

  console.log('\n=== it opens ===');
  const w = await app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    return { visible: win.isVisible(), title: win.getTitle(), b: win.getBounds() };
  });
  check('the window is on screen', w.visible === true);
  check('it has a real size', w.b.width > 800 && w.b.height > 500, `${w.b.width}x${w.b.height}`);
  check('it starts on an untitled document', /^Untitled — PatternFront$/.test(w.title), w.title);
  await page.screenshot({ path: path.join(SHOTS, '01-open.png') });

  console.log('\n=== drawing ===');
  const before = (await state()).json;
  const box = await page.evaluate(() => {
    const r = document.getElementById('cv').getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  check('the canvas has a layout box', box.w > 100 && box.h > 20,
        `${Math.round(box.w)}x${Math.round(box.h)}`);
  const y = box.y + box.h * 0.5;
  await page.mouse.move(box.x + box.w * 0.15, y);
  await page.mouse.down();
  for (let i = 1; i <= 10; i++) await page.mouse.move(box.x + box.w * (0.15 + i * 0.05), y);
  await page.mouse.up();
  await page.waitForTimeout(400);

  const drawn = await state();
  check('a stroke changes the document', drawn.json !== before);
  check('a stroke marks it dirty', drawn.dirty === true);
  check('the title shows the unsaved dot', (await title()).startsWith('•'), await title());

  console.log('\n=== duotone belongs to the preview ===');
  // The canvas draws structure; only the preview carries the chosen colours.
  await page.evaluate(() => document.getElementById('duos').children[10].click());
  await page.waitForTimeout(400);
  const onCanvas = await colours('cv');
  const onPreview = await colours('pvC');
  check('the canvas stays paper and ink',
        JSON.stringify(onCanvas) === JSON.stringify(['0,0,0', '255,255,255']),
        JSON.stringify(onCanvas));
  check('the preview carries the duotone',
        onPreview.length > 0 && JSON.stringify(onPreview) !== JSON.stringify(onCanvas),
        JSON.stringify(onPreview));

  console.log('\n=== the map view ===');
  await page.evaluate(() => document.getElementById('pvMap').click());
  await page.waitForTimeout(400);
  const atOrigin = await page.evaluate(() => document.getElementById('pvZ').textContent);
  check('it reports a world position', /·\s*0,0/.test(atOrigin), atOrigin);
  const pv = await page.evaluate(() => {
    const r = document.getElementById('pvC').getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  await page.mouse.move(pv.x + pv.w * 0.5, pv.y + pv.h * 0.5);
  await page.mouse.down();
  await page.mouse.move(pv.x + pv.w * 0.9, pv.y + pv.h * 0.75, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const moved = await page.evaluate(() => document.getElementById('pvZ').textContent);
  check('dragging moves the territory', moved !== atOrigin, moved);
  // Panning past the origin is the case a remainder-based sampler gets wrong.
  check('it survives negative world coordinates', /−|-\d/.test(moved.replace('·', '')), moved);
  check('the territory still renders there', (await colours('pvC')).length >= 2);
  await page.screenshot({ path: path.join(SHOTS, '02-map.png') });
  await page.evaluate(() => document.getElementById('pvMap').click());

  console.log('\n=== save, and open it again ===');
  await app.evaluate(({ dialog }, target) => {
    dialog.showSaveDialog = async () => ({ canceled: false, filePath: target });
  }, savePath);
  await cmd('file.saveAs');
  await page.waitForFunction(() => window.__pfState().path !== null, null, { timeout: 15_000 })
    .catch(() => {});

  const saved = await state();
  check('the file is on disk', existsSync(savePath), savePath);
  check('the editor knows its path', saved.path === savePath, String(saved.path));
  check('saving clears the dirty flag', saved.dirty === false);
  if (existsSync(savePath)) {
    const raw = readFileSync(savePath, 'utf8');
    let ok = true;
    try { JSON.parse(raw); } catch (e) { ok = false; check('the file is valid JSON', false, e.message); }
    if (ok) {
      check('the file is valid JSON', true, `${raw.length} bytes`);
      check('it matches what the editor holds', raw === saved.json);
    }
  }
  check('the atomic write left no temp file',
        readdirSync(path.dirname(savePath)).filter(f => f.endsWith('.tmp')).length === 0);
  check('the title shows the file name, no dot',
        (await title()) === 'round-trip.patternfront — PatternFront', await title());

  await cmd('file.new');
  await page.waitForTimeout(500);
  const blank = await state();
  check('New clears the document', blank.json !== saved.json);
  check('New clears the path', blank.path === null, String(blank.path));

  await cmd('file.openPath', savePath);
  await page.waitForFunction(() => window.__pfState().path !== null, null, { timeout: 15_000 })
    .catch(() => {});
  await page.waitForTimeout(500);
  const reopened = await state();
  check('reopening round-trips byte-identically', reopened.json === saved.json);
  check('the reopened document is clean', reopened.dirty === false);

  check('no renderer errors during the run', errors.length === 0, errors.slice(0, 3).join(' | '));
} catch (err) {
  check('the driver completed', false, (err.stack || err.message).split('\n').slice(0, 3).join(' '));
} finally {
  // The app guards close on unsaved changes; destroy bypasses that prompt.
  await app.evaluate(({ BrowserWindow }) => {
    for (const win of BrowserWindow.getAllWindows()) win.destroy();
  }).catch(() => {});
  await app.close().catch(() => {});
}

const failed = results.filter(r => !r.ok);
console.log();
if (failed.length) {
  console.log(`*** ${failed.length} FAILURE(S) ***`);
  for (const f of failed) console.log(`    - ${f.name}${f.detail ? '  ' + f.detail : ''}`);
  process.exit(1);
}
console.log(`ALL ${results.length} END-TO-END CHECKS PASSED`);
