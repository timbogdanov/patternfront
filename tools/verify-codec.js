#!/usr/bin/env node
/*
 * Run the EDITOR'S OWN encodeOF/decodeOF against the whole fixture corpus.
 *
 * tools/gen-codec-fixtures.py proves its own Python codec is self-consistent.
 * That is not the same as proving the shipping JavaScript agrees with it — and
 * the JS is what users' patterns actually go through. This lifts the real
 * functions out of app/patternfront.html and runs them over every fixture:
 *
 *   decode(fixture) -> re-encode -> must equal the fixture byte for byte
 *   header must round-trip width, height and scale exactly
 *
 * A disagreement between the two implementations shows up here rather than in
 * somebody's exported pattern.
 *
 *   node tools/verify-codec.js
 */

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { editorJs, grabFunction } = require('./lib/extract');

const ROOT = path.join(__dirname, '..');
const APP = path.join(ROOT, 'app', 'patternfront.html');
const FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'codec.json');

if (!fs.existsSync(FIXTURES)) {
  console.log(`missing ${FIXTURES}`);
  console.log('run: python3 tools/gen-codec-fixtures.py');
  process.exit(2);
}

const js = editorJs();

const ctx = {
  Uint8Array, Error,
  btoa: s => Buffer.from(s, 'binary').toString('base64'),
  atob: s => Buffer.from(s, 'base64').toString('binary'),
};
vm.createContext(ctx);
vm.runInContext([grabFunction(js, 'encodeOF'), grabFunction(js, 'decodeOF')].join('\n'), ctx);
const encodeOF = (w, h, s, b) => vm.runInContext('encodeOF', ctx)(w, h, s, b);
const decodeOF = d => vm.runInContext('decodeOF', ctx)(d);

const corpus = JSON.parse(fs.readFileSync(FIXTURES, 'utf8'));
const fixtures = corpus.patterns;

let failures = [];
let widest = 0, tallest = 0, longest = 0;
const scales = new Set();

for (const f of fixtures) {
  let d;
  try { d = decodeOF(f.patternData); }
  catch (e) { failures.push(`${f.name}: decodeOF threw ${e.message}`); continue; }

  if (d.w !== f.width || d.h !== f.height || d.scale !== f.scale) {
    failures.push(`${f.name}: header ${d.w}x${d.h}@${d.scale} != ${f.width}x${f.height}@${f.scale}`);
    continue;
  }
  const ink = d.bits.reduce((a, b) => a + b, 0);
  if (ink !== f.ink) {
    failures.push(`${f.name}: ${ink} set bits, corpus says ${f.ink}`);
    continue;
  }
  const back = encodeOF(d.w, d.h, d.scale, d.bits);
  if (back !== f.patternData) {
    failures.push(`${f.name}: re-encode differs (${back.length} vs ${f.patternData.length} chars)`);
    continue;
  }
  widest = Math.max(widest, f.width);
  tallest = Math.max(tallest, f.height);
  longest = Math.max(longest, f.patternData.length);
  scales.add(f.scale);
}

console.log(`${fixtures.length} fixtures through the editor's own codec`);
console.log(`  widths to ${widest}  heights to ${tallest}  `
          + `scales ${[...scales].sort((a, b) => a - b).join(',')}  `
          + `longest ${longest}/${corpus.maxChars} chars`);

if (failures.length) {
  console.log(`\n*** ${failures.length} FAILURE(S) ***`);
  for (const f of failures.slice(0, 20)) console.log('   ', f);
  process.exit(1);
}
console.log('  the shipping JavaScript agrees with the corpus byte for byte');
console.log('ALL CODEC CHECKS PASSED');
