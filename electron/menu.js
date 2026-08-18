'use strict';
/**
 * The native menu.
 *
 * Every item sends a command id to the renderer, which looks it up in the
 * COMMANDS table in app/patternfront.html. Menu items and on-screen buttons
 * therefore call the same function — a menu entry cannot drift away from the
 * behaviour of its twin in the sidebar.
 *
 * Accelerators listed here are owned by the menu. The renderer's own keydown
 * handler skips them when running on the desktop (MENU_KEYS), because Electron
 * fires the accelerator before the page sees the key and every one of them
 * would otherwise run twice.
 */

const { Menu, app, shell } = require('electron');

const REPO = 'https://github.com/timbogdanov/patternfront';
const isMac = process.platform === 'darwin';

function build({ send, recent, openRecent, quit }) {
  const cmd = (label, id, accelerator, extra = {}) => ({
    label, accelerator, click: () => send(id), ...extra,
  });

  const recentItems = recent.list.length
    ? [
        ...recent.list.map(file => ({
          label: file.replace(app.getPath('home'), '~'),
          click: () => openRecent(file),
        })),
        { type: 'separator' },
        { label: 'Clear Menu', click: () => recent.clear() },
      ]
    : [{ label: 'No Recent Patterns', enabled: false }];

  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' },
        { label: 'Quit PatternFront', accelerator: 'Cmd+Q', click: quit },
      ],
    }] : []),

    {
      label: '&File',
      submenu: [
        cmd('New Pattern', 'file.new', 'CmdOrCtrl+N'),
        cmd('Open…', 'file.open', 'CmdOrCtrl+O'),
        { label: 'Open Recent', submenu: recentItems },
        { type: 'separator' },
        cmd('Save', 'file.save', 'CmdOrCtrl+S'),
        cmd('Save As…', 'file.saveAs', 'CmdOrCtrl+Shift+S'),
        { type: 'separator' },
        {
          label: 'Export',
          submenu: [
            cmd('PNG — Current Frame…', 'export.png', 'CmdOrCtrl+E'),
            cmd('PNG — Sprite Sheet…', 'export.sheet'),
            cmd('Animated GIF…', 'export.gif'),
            { type: 'separator' },
            cmd('OpenFront patternData…', 'export.pattern', 'CmdOrCtrl+Shift+E'),
          ],
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { label: 'Quit', accelerator: 'Alt+F4', click: quit },
      ],
    },

    {
      label: '&Edit',
      submenu: [
        cmd('Undo', 'edit.undo', 'CmdOrCtrl+Z'),
        cmd('Redo', 'edit.redo', isMac ? 'Cmd+Shift+Z' : 'Ctrl+Y'),
        { type: 'separator' },
        cmd('Select All', 'edit.selectAll', 'CmdOrCtrl+A'),
        cmd('Deselect', 'edit.deselect', 'CmdOrCtrl+D'),
        { type: 'separator' },
        cmd('Clear', 'edit.clear', 'Delete'),
        cmd('Clear Every Layer', 'edit.clearAll', 'Shift+Delete'),
      ],
    },

    {
      label: '&View',
      submenu: [
        cmd('Zoom In', 'view.zoomIn', 'CmdOrCtrl+Plus'),
        cmd('Zoom Out', 'view.zoomOut', 'CmdOrCtrl+-'),
        cmd('Fit to Window', 'view.fit', 'CmdOrCtrl+Shift+0'),
        { type: 'separator' },
        {
          label: 'Interface Scale',
          submenu: [1, 1.5, 2, 2.5, 3].map(v => ({
            label: `${v}×`,
            click: () => send('view.scale', v),
          })),
        },
        cmd('Toggle Grid', 'view.grid'),
        cmd('Hide Panels', 'view.zen', 'Tab'),
        { type: 'separator' },
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { role: 'togglefullscreen' },
      ],
    },

    { label: '&Window', role: 'windowMenu' },

    {
      label: '&Help',
      submenu: [
        cmd('Keyboard Shortcuts', 'help.shortcuts'),
        { type: 'separator' },
        { label: 'Documentation', click: () => shell.openExternal(`${REPO}#readme`) },
        { label: 'Report an Issue', click: () => shell.openExternal(`${REPO}/issues/new`) },
        ...(isMac ? [] : [{ type: 'separator' }, { role: 'about' }]),
      ],
    },
  ];

  return Menu.buildFromTemplate(template);
}

function install(opts) {
  Menu.setApplicationMenu(build(opts));
}

module.exports = { build, install, REPO };
