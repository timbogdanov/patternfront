'use strict';
/**
 * Document and export file handling for the main process.
 *
 * A .patternfront file is exactly what `serialiseDoc()` produces in the
 * renderer — versioned JSON with base64 cel data. There is deliberately no
 * second format: the same string the autosave writes to localStorage is the
 * string that goes to disk, so both paths are covered by the same tests.
 */

const fs = require('fs/promises');
const path = require('path');
const { app, dialog } = require('electron');

const EXT = 'patternfront';
const DOC_FILTERS = [
  { name: 'PatternFront pattern', extensions: [EXT] },
  { name: 'All files', extensions: ['*'] },
];

// A document is small (a 129x65 pattern is a few KB) but a hand-edited or
// hostile file should not be able to make us allocate wildly.
const MAX_DOC_BYTES = 32 * 1024 * 1024;

const EXPORT_FILTERS = {
  '.png': [{ name: 'PNG image', extensions: ['png'] }],
  '.gif': [{ name: 'Animated GIF', extensions: ['gif'] }],
  '.json': [{ name: 'JSON', extensions: ['json'] }],
};

/** Reject anything that is not a plausible document before parsing it. */
async function readDocument(file) {
  const stat = await fs.stat(file);
  if (!stat.isFile()) throw new Error('not a file');
  if (stat.size > MAX_DOC_BYTES) {
    throw new Error(`${(stat.size / 1048576).toFixed(1)} MB is too large for a pattern`);
  }
  const text = await fs.readFile(file, 'utf8');
  // Parse here so a corrupt file fails in the main process with a real dialog
  // rather than silently returning nothing to the renderer.
  const doc = JSON.parse(text);
  if (!doc || doc.v !== 1 || !Array.isArray(doc.frames) || !doc.frames.length) {
    throw new Error('not a PatternFront document');
  }
  return text;
}

async function openDocument(win, recent) {
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    title: 'Open pattern',
    filters: DOC_FILTERS,
    properties: ['openFile'],
  });
  if (canceled || !filePaths.length) return null;
  return openPath(win, filePaths[0], recent);
}

async function openPath(win, file, recent) {
  try {
    const data = await readDocument(file);
    recent.add(file);
    return { path: file, data };
  } catch (err) {
    await dialog.showMessageBox(win, {
      type: 'error',
      message: 'Could not open that file',
      detail: `${path.basename(file)} — ${err.message}`,
      buttons: ['OK'],
    });
    return null;
  }
}

async function saveDocument(win, file, json, recent) {
  let target = file;
  if (!target) {
    const { canceled, filePath } = await dialog.showSaveDialog(win, {
      title: 'Save pattern',
      defaultPath: path.join(app.getPath('documents'), `untitled.${EXT}`),
      filters: DOC_FILTERS,
    });
    if (canceled || !filePath) return null;
    target = filePath.endsWith(`.${EXT}`) ? filePath : `${filePath}.${EXT}`;
  }
  try {
    await writeAtomic(target, json);
    recent.add(target);
    return target;
  } catch (err) {
    await dialog.showMessageBox(win, {
      type: 'error',
      message: 'Could not save',
      detail: `${target} — ${err.message}`,
      buttons: ['OK'],
    });
    return null;
  }
}

/**
 * Write to a sibling temp file and rename over the target.
 *
 * rename(2) is atomic within a filesystem, so an interrupted save leaves the
 * previous version intact instead of a half-written file. Losing artwork to a
 * crash mid-write is exactly the kind of thing people never forgive.
 */
async function writeAtomic(target, contents) {
  const tmp = `${target}.${process.pid}.tmp`;
  await fs.writeFile(tmp, contents, 'utf8');
  try {
    await fs.rename(tmp, target);
  } catch (err) {
    await fs.rm(tmp, { force: true });
    throw err;
  }
}

async function saveExport(win, name, bytes) {
  const ext = path.extname(name).toLowerCase();
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: 'Export',
    defaultPath: path.join(app.getPath('downloads'), name),
    filters: EXPORT_FILTERS[ext] || [{ name: 'All files', extensions: ['*'] }],
  });
  if (canceled || !filePath) return null;
  try {
    await fs.writeFile(filePath, Buffer.from(bytes));
    return filePath;
  } catch (err) {
    await dialog.showMessageBox(win, {
      type: 'error',
      message: 'Could not export',
      detail: `${filePath} — ${err.message}`,
      buttons: ['OK'],
    });
    return null;
  }
}

/** Recent documents, mirrored into the OS list and kept for the File menu. */
function makeRecent(onChange) {
  const LIMIT = 10;
  let list = [];
  return {
    get list() { return list.slice(); },
    add(file) {
      list = [file, ...list.filter(f => f !== file)].slice(0, LIMIT);
      app.addRecentDocument(file);
      onChange();
    },
    clear() {
      list = [];
      app.clearRecentDocuments();
      onChange();
    },
  };
}

module.exports = {
  EXT, MAX_DOC_BYTES,
  readDocument, openDocument, openPath, saveDocument, saveExport,
  writeAtomic, makeRecent,
};
