'use strict';
/**
 * The only bridge between the renderer and Node.
 *
 * The renderer is sandboxed with context isolation on and node integration off,
 * so this is the entire native surface it can reach. Everything here is a fixed
 * channel with validated arguments — the renderer cannot name an arbitrary IPC
 * channel, read an arbitrary path, or hand the main process a function.
 *
 * Keep this list short. Every entry is something a compromised renderer could
 * call, so each one has to be worth it.
 */

const { contextBridge, ipcRenderer } = require('electron');

const str = (v, name) => {
  if (typeof v !== 'string') throw new TypeError(`${name} must be a string`);
  return v;
};

contextBridge.exposeInMainWorld('pfNative', {
  isDesktop: true,
  platform: process.platform,

  /** → { path, data } for the chosen file, or null if cancelled. */
  openDocument: () => ipcRenderer.invoke('doc:open'),

  /** Read a specific path — only ever a path the main process handed us. */
  readDocument: (file) => ipcRenderer.invoke('doc:read', str(file, 'file')),

  /** path=null means Save As. → the path written, or null if cancelled. */
  saveDocument: (file, json) =>
    ipcRenderer.invoke('doc:save', file === null ? null : str(file, 'file'),
                       str(json, 'json')),

  /** Save exported bytes. → the path written, or null if cancelled. */
  saveExport: (name, bytes) => {
    if (!(bytes instanceof Uint8Array)) throw new TypeError('bytes must be a Uint8Array');
    // Copy into a plain array buffer so the structured clone is a byte payload
    // and not a view onto renderer memory.
    return ipcRenderer.invoke('export:save', str(name, 'name'), new Uint8Array(bytes));
  },

  setDirty: (v) => ipcRenderer.send('doc:dirty', !!v),
  setDocumentPath: (p) => ipcRenderer.send('doc:path', p === null ? null : str(p, 'path')),

  /** Menu → renderer. The callback receives (commandId, arg). */
  onCommand: (fn) => {
    if (typeof fn !== 'function') throw new TypeError('onCommand needs a function');
    ipcRenderer.on('command', (_e, id, arg) => fn(String(id), arg));
  },

  /** Open a URL in the user's browser. http(s) only — enforced in main too. */
  openExternal: (url) => ipcRenderer.send('shell:external', str(url, 'url')),
});
