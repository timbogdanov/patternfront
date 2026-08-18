'use strict';
/**
 * Remember where the window was.
 *
 * Small enough not to warrant a dependency. Bounds are clamped to a display
 * that actually exists, so a window saved on an external monitor does not open
 * off-screen once that monitor is unplugged.
 */

const fs = require('fs');
const path = require('path');
const { app, screen } = require('electron');

const FILE = () => path.join(app.getPath('userData'), 'window-state.json');
const DEFAULTS = { width: 1440, height: 900, maximised: false };
const MIN_WIDTH = 900;
const MIN_HEIGHT = 600;

function read() {
  try {
    const s = JSON.parse(fs.readFileSync(FILE(), 'utf8'));
    if (typeof s.width !== 'number' || typeof s.height !== 'number') return { ...DEFAULTS };
    return s;
  } catch {
    return { ...DEFAULTS };
  }
}

/** Bounds that are guaranteed to land on a connected display. */
function restore() {
  const s = read();
  const bounds = {
    width: Math.max(MIN_WIDTH, Math.round(s.width)),
    height: Math.max(MIN_HEIGHT, Math.round(s.height)),
  };

  if (typeof s.x === 'number' && typeof s.y === 'number') {
    const visible = screen.getAllDisplays().some(d => {
      const a = d.workArea;
      // Require a decent overlap, not just a touching corner.
      return s.x < a.x + a.width - 80 && s.x + bounds.width > a.x + 80
          && s.y < a.y + a.height - 40 && s.y + bounds.height > a.y;
    });
    if (visible) { bounds.x = Math.round(s.x); bounds.y = Math.round(s.y); }
  }
  return { bounds, maximised: !!s.maximised, minWidth: MIN_WIDTH, minHeight: MIN_HEIGHT };
}

/** Persist on move/resize/maximise. Debounced — resizing fires continuously. */
function track(win) {
  let timer = null;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (win.isDestroyed()) return;
      // getNormalBounds is the un-maximised geometry, which is what we want to
      // restore to when the user un-maximises later.
      const b = win.getNormalBounds();
      const state = { ...b, maximised: win.isMaximized() };
      try {
        fs.mkdirSync(path.dirname(FILE()), { recursive: true });
        fs.writeFileSync(FILE(), JSON.stringify(state, null, 1));
      } catch { /* a window position is not worth surfacing an error for */ }
    }, 400);
  };

  for (const ev of ['resize', 'move', 'maximize', 'unmaximize']) win.on(ev, save);
  win.on('close', () => clearTimeout(timer));
}

module.exports = { restore, track };
