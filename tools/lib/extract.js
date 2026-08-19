'use strict';
/*
 * Lift real functions out of app/patternfront.html so tests run the shipping
 * code rather than a copy of it.
 *
 * The editor is one HTML file on purpose — the same file is the browser build
 * and the desktop renderer — so there is no module boundary to import across.
 * The suites therefore slice functions out of the <script> block and evaluate
 * them in a vm context. That worked, but the brace matcher had been copied into
 * two files and was about to be copied into a third, which is one edit away from
 * two suites disagreeing about what the editor's source says.
 *
 *   const { editorJs, grabFunction } = require('./lib/extract');
 */

const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', '..', 'app', 'patternfront.html');

/** Every <script> body in the editor, concatenated. */
function editorJs() {
  const src = fs.readFileSync(APP, 'utf8');
  return [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
}

/**
 * Index of the `}` closing the `{` at `from`.
 *
 * Comments, strings and template literals are skipped, and a backslash escapes
 * the next character — without that last part `/\//g` reads as the start of a
 * line comment and the match runs off the end of the file.
 */
function matchBrace(text, from) {
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
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return i; }
  }
  throw new Error('unbalanced braces from ' + from);
}

/** Source of `function <name>(...) { ... }`, braces balanced. */
function grabFunction(js, name) {
  let at = js.indexOf(`function ${name}(`);
  if (at < 0) throw new Error(`function ${name} not found in the editor`);
  // Include a preceding `async`; without it the extracted copy throws
  // "await is only valid in async functions" and reads as an app bug.
  if (js.slice(Math.max(0, at - 6), at) === 'async ') at -= 6;
  return js.slice(at, matchBrace(js, js.indexOf('{', js.indexOf(')', at))) + 1);
}

/** Source of a single-line `const <name> = ...;` declaration. */
function grabConst(js, name) {
  const m = new RegExp(`^\\s*const ${name}\\s*=.*$`, 'm').exec(js);
  if (!m) throw new Error(`const ${name} not found in the editor`);
  return m[0].trim();
}

module.exports = { APP, editorJs, matchBrace, grabFunction, grabConst };
