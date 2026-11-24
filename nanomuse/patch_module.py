#!/usr/bin/env python3
"""Point the nanoMuse MobileGym app at YOUR server (same origin, your /?ui=nanomuse page).

usage: patch_module.py <path to mobilegym/apps/nanoMuse>
Idempotent. Fails loudly if upstream text moved.
"""
import pathlib, sys

mod = pathlib.Path(sys.argv[1])

def sub(path, old, new, marker):
    p = mod / path
    t = p.read_text(encoding="utf-8")
    if marker in t:
        print(f"already patched: {path}")
        return
    if t.count(old) != 1:
        sys.exit(f"patch_module: expected exactly one match in {path}, found {t.count(old)}")
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"patched: {path}")

# 1) come up already connected to our own origin; no token, so the notification
#    WebSocket (which needs a nanoMuse server) stays off.
sub(
    "data/index.ts",
    "  ...defaults,\n",
    "  ...defaults,\n"
    "  // UAM embed: same-origin server, no token, no nanoMuse-server-only features\n"
    "  ...(import.meta.env.VITE_NANOMUSE_EMBED\n"
    "    ? { serverUrl: typeof window !== 'undefined' ? window.location.origin : '', token: '', notify: false, gui: false }\n"
    "    : {}),\n",
    "VITE_NANOMUSE_EMBED",
)

# 2) the frame loads UAM's chat page (main.py serves it at /?ui=nanomuse)
sub(
    "pages/MusePage.tsx",
    "    url.pathname = '/';\n",
    "    url.pathname = '/';\n"
    "    if (import.meta.env.VITE_NANOMUSE_EMBED) url.searchParams.set('ui', 'nanomuse');\n",
    "VITE_NANOMUSE_EMBED",
)
