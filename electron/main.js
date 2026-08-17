'use strict';
/**
 * PatternFront — Electron main process.
 *
 * The renderer is app/patternfront.html, unchanged from the browser build. It
 * feature-detects `window.pfNative`; without it the same file is a plain web
 * page. Nothing here is a fork of the editor.
 *
 * Serving over a registered `app://` scheme rather than `file://` buys a real
 * origin — so localStorage (the autosave) works reliably, and a Content
 * Security Policy can actually be enforced on the document.
 */

const fs = require('fs/promises');
const path = require('path');
const { app, BrowserWindow, dialog, ipcMain, protocol, net, shell } = require('electron');

const docs = require('./documents');
const menu = require('./menu');
const windowState = require('./window-state');

const ROOT = path.join(__dirname, '..');
const APP_DIR = path.join(ROOT, 'app');
const ENTRY = 'app://patternfront/patternfront.html';
const SMOKE = process.argv.includes('--smoke');
// `electron . --shot out.png` renders the window offscreen and writes a PNG.
// Used for README images and for eyeballing a CI build without a display.
const SHOT = (() => {
  const i = process.argv.indexOf('--shot');
  return i >= 0 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : null;
})();

let win = null;
let recent = null;
let docPath = null;
let dirty = false;
/** Set once the user has confirmed discarding changes, so `close` proceeds. */
let forceClose = false;
/** Paths queued by the OS before the window existed (double-click to open). */
let pendingOpen = null;

// The custom scheme must be privileged before `ready`, or it gets no origin
// and localStorage throws — the exact failure that once made this app render
// as a blank page in a sandboxed frame.
protocol.registerSchemesAsPrivileged([{
  scheme: 'app',
  privileges: { standard: true, secure: true, supportFetchAPI: true },
}]);

/* ── serving the renderer ────────────────────────────────────────────── */

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

// Only files under app/ are reachable, and only after resolving the path — so
// `app://patternfront/../../etc/passwd` cannot escape the directory.
async function serve(request) {
  const url = new URL(request.url);
  const rel = decodeURIComponent(url.pathname).replace(/^\/+/, '');
  const file = path.resolve(APP_DIR, rel);
  if (file !== APP_DIR && !file.startsWith(APP_DIR + path.sep)) {
    return new Response('forbidden', { status: 403 });
  }
  try {
    const body = await fs.readFile(file);
    return new Response(body, {
      headers: {
        'content-type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
        // The editor is entirely self-contained: no network, no CDN, no eval.
        'content-security-policy':
          "default-src 'none'; img-src 'self' data: blob:; " +
          "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; " +
          "font-src 'self'; connect-src 'self' blob: data:; form-action 'none'; " +
          "base-uri 'none'; frame-ancestors 'none'",
      },
    });
  } catch {
    return new Response('not found', { status: 404 });
  }
}

/* ── window ──────────────────────────────────────────────────────────── */

function createWindow() {
  const state = windowState.restore();

  win = new BrowserWindow({
    ...state.bounds,
    minWidth: state.minWidth,
    minHeight: state.minHeight,
    show: false,
    backgroundColor: '#202125',           // --well, so there is no white flash
    title: 'PatternFront',
    // A normal title bar, deliberately. `hiddenInset` would drop the macOS
    // traffic lights straight on top of the app's own 24px top bar, and the
    // title is doing real work here — it carries the document name and the
    // unsaved-changes dot that setTitle() maintains.
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      webviewTag: false,
    },
  });

  if (state.maximised) win.maximize();
  windowState.track(win);

  win.once('ready-to-show', () => { if (!SMOKE && !SHOT) win.show(); });
  win.loadURL(ENTRY);

  // This app never navigates and never opens a second window. Anything that
  // tries is either a bug or something hostile; send links to the browser.
  win.webContents.on('will-navigate', (e, url) => {
    if (url !== ENTRY) { e.preventDefault(); openExternal(url); }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-attach-webview', e => e.preventDefault());

  win.on('close', onClose);
  win.on('closed', () => { win = null; });

  return win;
}

function openExternal(url) {
  // Never hand the shell anything but a web URL — file:// or a custom scheme
  // here would be a way to launch arbitrary things.
  try {
    const u = new URL(url);
    if (u.protocol === 'http:' || u.protocol === 'https:') shell.openExternal(url);
  } catch { /* not a URL; ignore */ }
}

/** Unsaved work must not disappear because someone hit the red button. */
function onClose(e) {
  if (forceClose || !dirty) return;
  e.preventDefault();
  const name = docPath ? path.basename(docPath) : 'this pattern';
  dialog.showMessageBox(win, {
    type: 'warning',
    message: `Save changes to ${name}?`,
    detail: 'Your changes will be lost if you don’t save them.',
    buttons: ['Save', "Don't Save", 'Cancel'],
    defaultId: 0,
    cancelId: 2,
  }).then(async ({ response }) => {
    if (response === 2) return;
    if (response === 1) { forceClose = true; win.close(); return; }
    // Ask the renderer for the current document, then save before closing.
    const json = await win.webContents.executeJavaScript('window.__pfState().json');
    const saved = await docs.saveDocument(win, docPath, json, recent);
    if (saved) { forceClose = true; win.close(); }
  });
}

function setTitle() {
  if (!win) return;
  const name = docPath ? path.basename(docPath) : 'Untitled';
  win.setTitle(`${dirty ? '• ' : ''}${name} — PatternFront`);
  win.setDocumentEdited?.(dirty);
  if (docPath) win.setRepresentedFilename?.(docPath);
}

const send = (id, arg) => win && win.webContents.send('command', id, arg);

function refreshMenu() {
  menu.install({
    send,
    recent,
    openRecent: async file => {
      const r = await docs.openPath(win, file, recent);
      if (r) send('file.openPath', r.path);
    },
    quit: () => { app.quit(); },
  });
}

/* ── opening files from the OS ───────────────────────────────────────── */

function queueOpen(file) {
  if (!file) return;
  if (win && !win.webContents.isLoading()) send('file.openPath', file);
  else pendingOpen = file;
}

/** Windows and Linux pass the file as an argv entry. */
function fileFromArgv(argv) {
  return argv.slice(1).find(a => a.toLowerCase().endsWith(`.${docs.EXT}`)) || null;
}

// macOS delivers this before `ready`, so it is registered at module scope.
app.on('open-file', (e, file) => { e.preventDefault(); queueOpen(file); });

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_e, argv) => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
    queueOpen(fileFromArgv(argv));
  });
}

/* ── IPC ─────────────────────────────────────────────────────────────── */

function wireIpc() {
  ipcMain.handle('doc:open', async () => {
    const r = await docs.openDocument(win, recent);
    if (r) refreshMenu();
    return r;
  });

  ipcMain.handle('doc:read', async (_e, file) => {
    try { return await docs.readDocument(file); }
    catch { return null; }
  });

  ipcMain.handle('doc:save', async (_e, file, json) => {
    const p = await docs.saveDocument(win, file, json, recent);
    if (p) refreshMenu();
    return p;
  });

  ipcMain.handle('export:save', (_e, name, bytes) =>
    docs.saveExport(win, path.basename(String(name)), bytes));

  ipcMain.on('doc:dirty', (_e, v) => { dirty = !!v; setTitle(); });
  ipcMain.on('doc:path', (_e, p) => { docPath = p || null; setTitle(); });
  ipcMain.on('shell:external', (_e, url) => openExternal(url));
}

/* ── smoke test ──────────────────────────────────────────────────────── */

/**
 * `electron . --smoke` — prove the app actually runs, not merely that it built.
 * Loads the real renderer offscreen, asserts the editor came up and the native
 * bridge is wired, then exits 0 or 1. This is what CI runs under xvfb.
 */
async function smoke() {
  const checks = [];
  const t0 = Date.now();

  // Collected in the main process rather than from a renderer global: a script
  // that dies before it can install a handler would otherwise report clean.
  const consoleErrors = [];
  win.webContents.on('console-message', (e) => {
    if (e.level === 'error') consoleErrors.push(`${e.message} (${e.sourceId}:${e.lineNumber})`);
  });
  win.webContents.on('preload-error', (_e, file, err) =>
    consoleErrors.push(`preload ${path.basename(file)}: ${err.message}`));
  win.webContents.on('render-process-gone', (_e, d) =>
    consoleErrors.push(`renderer gone: ${d.reason}`));

  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('renderer never finished loading')), 30000);
      win.webContents.once('did-finish-load', () => { clearTimeout(timer); resolve(); });
      win.webContents.once('did-fail-load', (_e, code, desc) => {
        clearTimeout(timer); reject(new Error(`load failed ${code}: ${desc}`));
      });
    });

    const report = await win.webContents.executeJavaScript(`(() => {
      const q = s => document.querySelector(s);
      const cv = q('#cv');
      return {
        title: document.title,
        native: !!(window.pfNative && window.pfNative.isDesktop),
        bridge: !!(window.__pf && window.__pf.commands),
        commands: window.__pf ? Object.keys(window.__pf.commands).length : 0,
        app: !!q('.app'),
        canvasPainted: !!(cv && cv.width > 0 && cv.height > 0),
        rail: document.querySelectorAll('#rail button').length,
        stamps: document.querySelectorAll('#stamps button').length,
        elements: document.querySelectorAll('*').length,
      };
    })()`);

    const expect = (name, ok, detail) => checks.push({ name, ok, detail });
    expect('title is PatternFront', report.title === 'PatternFront', report.title);
    expect('native bridge installed', report.native === true);
    expect('command table exposed', report.bridge && report.commands >= 15,
           `${report.commands} commands`);
    expect('editor root rendered', report.app === true);
    expect('canvas has real dimensions', report.canvasPainted === true);
    expect('tool rail built', report.rail > 5, `${report.rail} tools`);
    expect('stamps built', report.stamps >= 50, `${report.stamps} stamps`);
    expect('document is populated', report.elements > 300, `${report.elements} elements`);
    expect('no console errors', consoleErrors.length === 0,
           consoleErrors.slice(0, 3).join(' | '));
  } catch (err) {
    checks.push({ name: 'renderer loaded', ok: false, detail: err.message });
  }

  for (const c of checks) {
    console.log(`  [${c.ok ? 'PASS' : 'FAIL'}] ${c.name}${c.detail ? '  ' + c.detail : ''}`);
  }
  const failed = checks.filter(c => !c.ok).length;
  console.log(failed
    ? `\n*** ${failed} FAILURE(S) ***`
    : `\nSMOKE TEST PASSED  (${Date.now() - t0} ms)`);
  app.exit(failed ? 1 : 0);
}

/** Render the window offscreen and write it to a PNG. */
async function shoot() {
  try {
    await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('load timed out')), 30000);
      win.webContents.once('did-finish-load', () => { clearTimeout(t); resolve(); });
    });
    // Let the first paint, the fit-to-window rAF and the restore toast settle.
    await new Promise(r => setTimeout(r, 1200));
    const image = await win.webContents.capturePage();
    await fs.writeFile(SHOT, image.toPNG());
    const { width, height } = image.getSize();
    console.log(`wrote ${SHOT}  (${width}x${height})`);
    app.exit(0);
  } catch (err) {
    console.error('screenshot failed:', err.message);
    app.exit(1);
  }
}

/* ── lifecycle ───────────────────────────────────────────────────────── */

app.whenReady().then(() => {
  protocol.handle('app', serve);
  app.setAboutPanelOptions?.({
    applicationName: 'PatternFront',
    applicationVersion: app.getVersion(),
    website: menu.REPO,
  });

  recent = docs.makeRecent(() => refreshMenu());
  wireIpc();
  createWindow();
  refreshMenu();

  win.webContents.once('did-finish-load', () => {
    const queued = pendingOpen || fileFromArgv(process.argv);
    if (queued) { pendingOpen = null; send('file.openPath', queued); }
  });

  if (SMOKE) smoke();
  else if (SHOT) shoot();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) { createWindow(); refreshMenu(); }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
