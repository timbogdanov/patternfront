#!/usr/bin/env python3
"""
Check the Electron shell's security posture and packaging config.

An open-source Electron app gets read by strangers, and the default-insecure
knobs (nodeIntegration, a disabled sandbox, an unrestricted window.open) are
exactly what people look for first. These are cheap greps, but they are what
stops a convenient shortcut during a late-night debugging session shipping.

Run:  python3 tools/verify-electron.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(ROOT, "electron")

fails: list[str] = []


def chk(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def read(name: str) -> str:
    p = os.path.join(E, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def main() -> int:
    main_js = read("main.js")
    preload = read("preload.js")
    menu = read("menu.js")
    documents = read("documents.js")
    if not main_js:
        print("electron/main.js not found")
        return 2

    print("=== renderer sandbox ===")
    chk("context isolation on", "contextIsolation: true" in main_js)
    chk("node integration off", "nodeIntegration: false" in main_js)
    chk("sandbox on", "sandbox: true" in main_js)
    chk("webview tag disabled",
        "webviewTag: false" in main_js and "will-attach-webview" in main_js)
    chk("a preload is set", "preload: path.join(__dirname, 'preload.js')" in main_js)
    # `true` for any of these would undo the rest of the list.
    for bad in ("nodeIntegration: true", "contextIsolation: false",
                "sandbox: false", "webSecurity: false", "allowRunningInsecureContent"):
        chk(f"never sets {bad}", bad not in main_js)

    print("\n=== navigation ===")
    chk("navigation away from the app is blocked", "will-navigate" in main_js)
    chk("popups are denied", "setWindowOpenHandler" in main_js
        and "action: 'deny'" in main_js)
    chk("only http(s) reaches the shell",
        "u.protocol === 'http:' || u.protocol === 'https:'" in main_js)

    print("\n=== serving the renderer ===")
    chk("served over a registered scheme, not file://",
        "registerSchemesAsPrivileged" in main_js and "protocol.handle('app'" in main_js)
    chk("the scheme is standard and secure, so localStorage works",
        "standard: true" in main_js and "secure: true" in main_js)
    chk("a CSP is sent with the document", "content-security-policy" in main_js)
    for directive in ("default-src 'none'", "frame-ancestors 'none'",
                      "base-uri 'none'", "form-action 'none'"):
        chk(f"CSP has {directive!r}", directive in main_js)
    chk("path traversal out of app/ is refused",
        "path.resolve(APP_DIR, rel)" in main_js
        and "file.startsWith(APP_DIR + path.sep)" in main_js)

    print("\n=== the preload surface ===")
    exposed = set(re.findall(r"^\s{2}(\w+):", preload, re.M))
    declared = {"isDesktop", "platform", "openDocument", "readDocument",
                "saveDocument", "saveExport", "setDirty", "setDocumentPath",
                "onCommand", "openExternal"}
    chk("exposes exactly the declared surface", exposed == declared,
        f"extra={sorted(exposed - declared)} missing={sorted(declared - exposed)}")
    chk("uses contextBridge, not a raw window assignment",
        "contextBridge.exposeInMainWorld" in preload)
    chk("does not hand the renderer ipcRenderer itself",
        "exposeInMainWorld('ipcRenderer'" not in preload
        and "ipcRenderer," not in preload.replace("const { contextBridge, ipcRenderer }", ""))
    chk("arguments are type-checked before crossing", "const str = (v, name)" in preload)
    chk("no channel is chosen by the renderer",
        not re.search(r"ipcRenderer\.(invoke|send)\(\s*(channel|name|id)\b", preload))

    print("\n=== documents ===")
    chk("saves are atomic", "async function writeAtomic" in documents
        and "fs.rename(tmp, target)" in documents)
    chk("input size is bounded", "MAX_DOC_BYTES" in documents)
    chk("a document is validated before it is trusted",
        "doc.v !== 1" in documents and "Array.isArray(doc.frames)" in documents)
    chk("unsaved work prompts before the window closes",
        "function onClose" in main_js and "Save changes to" in main_js
        and "e.preventDefault()" in main_js)

    print("\n=== menu ===")
    chk("menu items dispatch command ids, not inline logic",
        "click: () => send(id)" in menu)
    for accel in ("CmdOrCtrl+N", "CmdOrCtrl+O", "CmdOrCtrl+S", "CmdOrCtrl+Shift+S",
                  "CmdOrCtrl+Z", "CmdOrCtrl+A", "CmdOrCtrl+D"):
        chk(f"{accel} is bound", accel in menu)
    chk("file associations are registered",
        "fileAssociations" in read_root("electron-builder.yml")
        and "ext: patternfront" in read_root("electron-builder.yml"))

    # Setting a custom application menu replaces the default one wholesale, and
    # on macOS the clipboard shortcuts in web content are delivered by the
    # menu. A menu with no Paste item leaves Cmd+V with nowhere to go and no
    # input in the app can be pasted into — which is how an API key becomes
    # untypeable. Every text-editing item must drive the web contents.
    chk("Edit items drive the web contents, not just the canvas",
        "win.webContents[action]()" in menu)
    for label, accel in (("Undo", "CmdOrCtrl+Z"), ("Cut", "CmdOrCtrl+X"),
                         ("Copy", "CmdOrCtrl+C"), ("Paste", "CmdOrCtrl+V"),
                         ("Select All", "CmdOrCtrl+A")):
        chk(f"{label} is in the Edit menu on {accel}",
            re.search(rf"edit\('{re.escape(label)}',[^)]*{re.escape(accel)}", menu) is not None)
    # A plain, unmodified key in the menu is swallowed application-wide, so a
    # bare `Delete` accelerator stops the key deleting characters in every text
    # field. The renderer's keydown owns it and already skips text fields.
    chk("no bare Delete accelerator to eat the key in text fields",
        "'Delete'" not in menu)
    # Electron ships no context menu; the canvas has its own, so without this a
    # text field gets neither and right-click offers no way to paste.
    chk("right-click offers paste inside a text field",
        "params.isEditable" in main_js and "'Paste', 'paste'" in main_js)

    print("\n=== packaging ===")
    yml = read_root("electron-builder.yml")
    chk("mac builds both architectures", "arch: [arm64, x64]" in yml)
    chk("windows gets an installer and a portable build",
        "target: nsis" in yml and "target: portable" in yml)
    chk("only the app ships, not the repo",
        "- electron/**/*" in yml and "- app/**/*" in yml and "tools/" not in yml)
    chk("signing is wired but inert", "hardenedRuntime: false" in yml
        and "entitlements: build/entitlements.mac.plist" in yml
        and os.path.exists(os.path.join(ROOT, "build", "entitlements.mac.plist")))
    chk("an icon exists for the build",
        os.path.exists(os.path.join(ROOT, "build", "icon.png")))
    # Packaging rewrites the bundle Electron shipped linker-signed. Without a
    # re-seal the signature no longer describes its contents, and macOS calls a
    # downloaded build "damaged" — a refusal the user cannot clear, unlike the
    # ordinary unidentified-developer one. Unquarantined builds run regardless,
    # so nothing else in this suite would notice.
    chk('the mac bundle is ad-hoc signed at minimum', 'identity: "-"' in yml)

    # The renderer may reach exactly one outbound origin, and only when the user
    # has set their own key. `https:` or `*` here would let a compromised renderer
    # phone anywhere; this check is what keeps the widening honest.
    print("\n=== outbound network ===")
    main = read("main.js")
    connect = re.search(r"connect-src ([^\"]+)", main)
    # The directive ends at the ';' that separates it from the next one.
    hosts = connect.group(1).split(";")[0].split() if connect else []
    chk("connect-src names the AI provider and nothing wider",
        "https://api.anthropic.com" in hosts
        and not any(h in ("https:", "*", "http:") for h in hosts),
        " ".join(hosts))
    chk("the key is never written into the packaged app",
        "sk-ant" not in read_root("app/patternfront.html"))

    print()
    if fails:
        print(f"*** {len(fails)} FAILURE(S) ***")
        for f in fails:
            print(f"    - {f}")
        return 1
    print("ALL ELECTRON CHECKS PASSED")
    return 0


def read_root(name: str) -> str:
    p = os.path.join(ROOT, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


if __name__ == "__main__":
    sys.exit(main())
