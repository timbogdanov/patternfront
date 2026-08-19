#!/usr/bin/env node
/*
 * Run the EDITOR'S OWN DSL against the Python oracle.
 *
 * tools/dsl_prototype.py is the reference implementation and tools/dsl_demo.py
 * proves 28 programs tile exactly. Neither says anything about the JavaScript a
 * user's pattern actually goes through. This lifts the real renderer out of
 * app/patternfront.html and re-renders every program in tests/fixtures/dsl.json,
 * comparing the encoded result byte for byte.
 *
 * Byte-for-byte is the right bar rather than "looks similar": four things in the
 * Python do not survive a literal translation, and each fails silently.
 *
 *   round()   banker's rounding, so round(2.5) is 2 where Math.round gives 3.
 *             It decides wave offsets and canvas sizing.
 *   %         a floor modulo in Python, a remainder in JS. Any expression that
 *             can go negative diverges.
 *   //        floors, where |0 truncates toward zero.
 *   _hash2    multiplies by constants near 2^31; a plain * passes 2^53 and drops
 *             low bits, so noise and dot jitter drift apart.
 *
 * A pattern that is one pixel different still encodes to a different string, so
 * any of those shows up here as a mismatch rather than as a subtly wrong export.
 *
 *   node tools/verify-dsl.js
 */

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { editorJs, grabFunction, grabConst } = require('./lib/extract');

const ROOT = path.join(__dirname, '..');
const FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'dsl.json');

if (!fs.existsSync(FIXTURES)) {
  console.log(`missing ${FIXTURES}`);
  console.log('run: python3 tools/gen-dsl-fixtures.py');
  process.exit(2);
}

const js = editorJs();
const ctx = {
  Uint8Array, Error, Math, JSON, Object, String, Array,
  btoa: s => Buffer.from(s, 'binary').toString('base64'),
};
vm.createContext(ctx);
vm.runInContext([
  grabConst(js, 'floorMod'),
  grabFunction(js, 'encodeOF'),
  grabFunction(js, 'pyRound'),
  grabFunction(js, 'gcd'),
  grabFunction(js, 'lcm'),
  grabFunction(js, 'hash2'),
  grabConst(js, 'F57'),
  grabConst(js, 'F35'),
  grabConst(js, 'DSL_MIN_W'),
  grabMulti('DSL_SHAPES'),
  grabConst(js, 'DSL_CANVAS_LOCKED'),
  grabMulti('DSL_RANGES'),
  grabFunction(js, 'dslValidateShape'),
  grabFunction(js, 'dslValidate'),
  grabFunction(js, 'dslSize'),
  grabFunction(js, 'dslRender'),
].join('\n'), ctx);

/** A multi-line `const NAME={...};` — grabConst only handles single lines. */
function grabMulti(name) {
  const at = js.indexOf(`const ${name}=`);
  if (at < 0) throw new Error(`const ${name} not found in the editor`);
  const { matchBrace } = require('./lib/extract');
  const open = js.indexOf('{', at);
  return js.slice(at, matchBrace(js, open) + 1) + ';';
}

const dslRender = vm.runInContext('dslRender', ctx);
const encodeOF = vm.runInContext('encodeOF', ctx);
const pyRound = vm.runInContext('pyRound', ctx);

const corpus = JSON.parse(fs.readFileSync(FIXTURES, 'utf8'));
const failures = [];

// State the rounding rule as a check, rather than leaving the fixture to imply
// it. If this is wrong, several cases below fail for a reason nobody would guess.
for (const [input, want] of [[0.5, 0], [1.5, 2], [2.5, 2], [3.5, 4], [-2.5, -2], [2.4, 2]]) {
  if (pyRound(input) !== want) {
    failures.push(`pyRound(${input}) is ${pyRound(input)}, Python gives ${want}`);
  }
}

// Compare the glyph tables directly. The editor keeps its own copy, and a bad
// transcription otherwise surfaces only as a lit-pixel count being off.
{
  const F57 = vm.runInContext('F57', ctx), F35 = vm.runInContext('F35', ctx);
  for (const [label, want, got] of [['5x7', corpus.fonts['5x7'], F57],
                                    ['3x5', corpus.fonts['3x5'], F35]]) {
    const wrong = Object.keys(want)
      .filter(k => JSON.stringify(want[k]) !== JSON.stringify(got[k]));
    if (wrong.length) {
      failures.push(`${label} font: ${wrong.length}/${Object.keys(want).length} `
                  + `glyphs differ from the source table (${wrong.slice(0, 8).join(' ')})`);
    }
  }
}

const primitives = new Set();
for (const c of corpus.cases) {
  let got;
  try { got = dslRender(c.program); }
  catch (e) { failures.push(`${c.name}: dslRender threw ${e.message}`); continue; }

  if (got.w !== c.width || got.h !== c.height) {
    failures.push(`${c.name}: sized ${got.w}x${got.h}, oracle says ${c.width}x${c.height}`);
    continue;
  }
  const ink = got.bits.reduce((a, b) => a + b, 0);
  if (ink !== c.ink) {
    failures.push(`${c.name}: ${ink} lit pixels, oracle says ${c.ink}`);
    continue;
  }
  const data = encodeOF(got.w, got.h, got.scale, got.bits);
  if (data !== c.patternData) {
    failures.push(`${c.name}: encodes to a different pattern `
                + `(${data.length} vs ${c.patternData.length} chars)`);
    continue;
  }
  for (const l of c.program.layers) primitives.add(l.shape.type);
}

console.log(`${corpus.cases.length} programs through the editor's own DSL`);
console.log(`  ${primitives.size} primitives exercised, `
          + `every result compared as encoded patternData`);

if (failures.length) {
  console.log(`\n*** ${failures.length} FAILURE(S) ***`);
  for (const f of failures.slice(0, 20)) console.log(`    - ${f}`);
  if (failures.length > 20) console.log(`    ... and ${failures.length - 20} more`);
  process.exit(1);
}
console.log('  the shipping renderer agrees with the oracle byte for byte');
console.log('ALL DSL CHECKS PASSED');
