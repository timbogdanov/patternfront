#!/usr/bin/env node
/*
 * Run the EDITOR'S OWN map-scale sampler against the oracle.
 *
 * OpenFront paints a pattern onto territory in absolute world coordinates: a
 * territory's appearance depends on where it sits on the map, not just on the
 * bitmap. `tools/preview_prototype.py` establishes that rule and
 * `tools/gen-sampler-fixtures.py` freezes it into tests/fixtures/sampler.json,
 * checked there against an independently written oracle. Neither proves the
 * shipping JavaScript agrees — and the JavaScript is what a user's preview
 * actually goes through. This lifts the real functions out of the editor and
 * runs them over every probe.
 *
 * The probes straddle the origin deliberately. JavaScript's `%` is a remainder
 * whose sign follows the dividend, so `-1 % 4` is `-1` where a floor modulo
 * gives `3`. A sampler using a bare `%` indexes before the start of the bit
 * array as soon as the territory is panned left of the origin. That is the
 * single most likely way for this port to be wrong, so more than half the
 * probes are negative.
 *
 *   node tools/verify-sampler.js
 */

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { editorJs, grabFunction, grabConst } = require('./lib/extract');

const ROOT = path.join(__dirname, '..');
const FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'sampler.json');

if (!fs.existsSync(FIXTURES)) {
  console.log(`missing ${FIXTURES}`);
  console.log('run: python3 tools/gen-sampler-fixtures.py');
  process.exit(2);
}

const js = editorJs();
const ctx = {
  Uint8Array, Error,
  atob: s => Buffer.from(s, 'base64').toString('binary'),
};
vm.createContext(ctx);
vm.runInContext([
  grabFunction(js, 'decodeOF'),
  grabConst(js, 'floorMod'),
  grabFunction(js, 'ofPrimaryAt'),
].join('\n'), ctx);

const decodeOF = vm.runInContext('decodeOF', ctx);
const ofPrimaryAt = vm.runInContext('ofPrimaryAt', ctx);
const floorMod = vm.runInContext('floorMod', ctx);

const corpus = JSON.parse(fs.readFileSync(FIXTURES, 'utf8'));
const probes = corpus.probes;
const failures = [];

// The trap itself, stated as a check rather than left to the fixture to imply.
if (floorMod(-1, 4) !== 3 || floorMod(-9, 4) !== 3 || floorMod(9, 4) !== 1) {
  failures.push(`floorMod is a remainder, not a floor modulo: `
              + `floorMod(-1,4)=${floorMod(-1, 4)} should be 3`);
}

let negativeProbes = 0;
for (const [x, y] of probes) if (x < 0 || y < 0) negativeProbes++;

const scales = new Set();
for (const c of corpus.cases) {
  let d;
  try { d = decodeOF(c.patternData); }
  catch (e) { failures.push(`${c.name}: decodeOF threw ${e.message}`); continue; }

  if (d.w !== c.width || d.h !== c.height || d.scale !== c.scale) {
    failures.push(`${c.name}: header ${d.w}x${d.h}@${d.scale} `
                + `!= ${c.width}x${c.height}@${c.scale}`);
    continue;
  }

  let wrong = 0, firstAt = null;
  for (let i = 0; i < probes.length; i++) {
    const got = ofPrimaryAt(d, probes[i][0], probes[i][1]) ? '1' : '0';
    if (got !== c.expect[i]) {
      if (firstAt === null) firstAt = probes[i];
      wrong++;
    }
  }
  if (wrong) {
    failures.push(`${c.name}: ${wrong}/${probes.length} probes disagree, `
                + `first at (${firstAt[0]},${firstAt[1]})`);
    continue;
  }
  scales.add(c.scale);
}

// The property that makes this a *map* preview rather than a tiled one: where a
// territory sits decides which part of the pattern lands on it. If sampling
// ignored the offset, every territory would look identical and the whole view
// would be a lie. A shift of one scaled period must be invisible; a shift of one
// world tile must not be, for a pattern that has any structure at all.
{
  const structured = corpus.cases.filter(c => c.width > 2 && c.scale <= 3);
  let sameUnderPeriod = 0, changedUnderTile = 0;
  for (const c of structured) {
    const d = decodeOF(c.patternData);
    const periodX = d.w << d.scale;
    const row = y => (x0) => {
      let out = '';
      for (let i = 0; i < 32; i++) out += ofPrimaryAt(d, x0 + i, y) ? '1' : '0';
      return out;
    };
    if (row(3)(0) !== row(3)(periodX)) sameUnderPeriod++;
    if (row(3)(0) !== row(3)(1)) changedUnderTile++;
  }
  if (sameUnderPeriod) {
    failures.push(`${sameUnderPeriod} pattern(s) changed after shifting a full `
                + `scaled period — the pattern is not tiling in world space`);
  }
  if (!changedUnderTile) {
    failures.push('no pattern changed when shifted one world tile — sampling is '
                + 'ignoring position, so every territory would look the same');
  }
  console.log(`  position matters: ${changedUnderTile}/${structured.length} `
            + `patterns change under a one-tile shift, none under a full period`);
}

console.log(`${corpus.cases.length} patterns × ${probes.length} probes `
          + `through the editor's own sampler`);
console.log(`  scales ${[...scales].sort((a, b) => a - b).join(',')}  `
          + `${negativeProbes} probes at negative world coordinates`);

if (failures.length) {
  console.log(`\n*** ${failures.length} FAILURE(S) ***`);
  for (const f of failures) console.log(`    - ${f}`);
  process.exit(1);
}
console.log('  the shipping sampler agrees with the oracle on every probe');
console.log('ALL SAMPLER CHECKS PASSED');
