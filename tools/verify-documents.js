#!/usr/bin/env node
/*
 * Exercise the desktop document layer without launching Electron.
 *
 * electron/documents.js does the file handling: validating what is opened,
 * writing atomically so a crash mid-save cannot destroy the previous version,
 * and refusing implausible input. Those are the paths where a bug loses
 * somebody's artwork, so they get tested directly rather than only through the
 * smoke test.
 *
 * `electron` is stubbed — the module only uses app.getPath and dialog, neither
 * of which is involved in the parts worth testing here.
 *
 *   node tools/verify-documents.js
 */

'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');

// Stub `electron` before requiring the module under test.
const stub = {
  app: {
    getPath: (n) => os.tmpdir(),
    addRecentDocument() {},
    clearRecentDocuments() {},
  },
  dialog: {
    showOpenDialog: async () => ({ canceled: true, filePaths: [] }),
    showSaveDialog: async () => ({ canceled: true, filePath: null }),
    showMessageBox: async () => ({ response: 0 }),
  },
};
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === 'electron') return 'electron-stub';
  return origResolve.call(this, request, ...rest);
};
require.cache['electron-stub'] = { id: 'electron-stub', filename: 'electron-stub',
                                   loaded: true, exports: stub };

const docs = require('../electron/documents.js');

let failures = 0;
const chk = (name, ok, detail) => {
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures++;
};

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pf-doc-'));
const p = (n) => path.join(tmp, n);

// A minimal but valid document, in the shape serialiseDoc() emits.
const VALID = JSON.stringify({
  v: 1, w: 4, h: 3,
  palette: [[0, 0, 0, 0], [255, 255, 255, 255], [0, 0, 0, 255]],
  layers: [['Layer 1', 1, 0, 1]],
  frames: [[Buffer.from([1, 1, 2, 2, 1, 1, 2, 2, 1, 1, 2, 2]).toString('base64')]],
});

(async () => {
  console.log('=== reading documents ===');

  fs.writeFileSync(p('good.patternfront'), VALID);
  const back = await docs.readDocument(p('good.patternfront'));
  chk('a valid document reads back byte-identically', back === VALID);

  const rejects = [
    ['not JSON at all', 'nope.patternfront', 'this is not json'],
    ['valid JSON that is not a document', 'wrong.patternfront', '{"hello":"world"}'],
    ['a future format version', 'v9.patternfront', '{"v":9,"frames":[[]]}'],
    ['a document with no frames', 'empty.patternfront', '{"v":1,"frames":[]}'],
    ['JSON null', 'null.patternfront', 'null'],
  ];
  for (const [label, file, body] of rejects) {
    fs.writeFileSync(p(file), body);
    let threw = null;
    try { await docs.readDocument(p(file)); } catch (e) { threw = e.message; }
    chk(`rejects ${label}`, threw !== null, threw || 'accepted it');
  }

  let threw = null;
  try { await docs.readDocument(p('does-not-exist')); } catch (e) { threw = e.code || e.message; }
  chk('a missing file raises rather than returning junk', threw !== null, String(threw));

  threw = null;
  try { await docs.readDocument(tmp); } catch (e) { threw = e.message; }
  chk('a directory is not a document', threw !== null, threw);

  // Oversized input must be refused before it is read into memory.
  const big = p('huge.patternfront');
  fs.writeFileSync(big, Buffer.alloc(docs.MAX_DOC_BYTES + 1024, 0x20));
  threw = null;
  try { await docs.readDocument(big); } catch (e) { threw = e.message; }
  chk('an oversized file is refused', threw !== null && /too large/.test(threw), threw);

  console.log('\n=== atomic writes ===');

  const target = p('atomic.patternfront');
  await docs.writeAtomic(target, VALID);
  chk('writes the file', fs.readFileSync(target, 'utf8') === VALID);

  await docs.writeAtomic(target, VALID.replace('"w":4', '"w":8'));
  chk('overwrites in place', /"w":8/.test(fs.readFileSync(target, 'utf8')));
  chk('leaves no temp file behind',
      fs.readdirSync(tmp).filter(f => f.endsWith('.tmp')).length === 0,
      fs.readdirSync(tmp).filter(f => f.endsWith('.tmp')).join(','));

  // If the rename cannot happen, the previous contents must survive intact —
  // this is the whole reason for writing to a temp file first.
  const readonlyDir = p('ro');
  fs.mkdirSync(readonlyDir);
  const guarded = path.join(readonlyDir, 'keep.patternfront');
  fs.writeFileSync(guarded, VALID);
  fs.chmodSync(readonlyDir, 0o500);
  threw = null;
  try { await docs.writeAtomic(guarded, 'REPLACED'); } catch (e) { threw = e.code; }
  chk('a failed write raises', threw !== null, String(threw));
  chk('and the previous version is untouched',
      fs.readFileSync(guarded, 'utf8') === VALID);
  fs.chmodSync(readonlyDir, 0o700);

  console.log('\n=== recent documents ===');
  let changes = 0;
  const recent = docs.makeRecent(() => changes++);
  recent.add('/a.patternfront');
  recent.add('/b.patternfront');
  recent.add('/a.patternfront');
  chk('most recent first, no duplicates',
      JSON.stringify(recent.list) === JSON.stringify(['/a.patternfront', '/b.patternfront']),
      JSON.stringify(recent.list));
  chk('every change notifies the menu', changes === 3, String(changes));
  for (let i = 0; i < 20; i++) recent.add(`/f${i}.patternfront`);
  chk('the list is capped', recent.list.length === 10, String(recent.list.length));
  recent.clear();
  chk('clearing empties it', recent.list.length === 0);

  fs.rmSync(tmp, { recursive: true, force: true });

  console.log();
  if (failures) {
    console.log(`*** ${failures} FAILURE(S) ***`);
    process.exit(1);
  }
  console.log('ALL DOCUMENT CHECKS PASSED');
})();
