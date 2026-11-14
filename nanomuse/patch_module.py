#!/usr/bin/env python3
"""Point the nanoMuse MobileGym app at YOUR server and let your agent operate the phone.

usage: patch_module.py <path to mobilegym/apps/nanoMuse>
Same-origin server (your /?ui=nanomuse chat), a per-browser token shared with the chat page
(localStorage 'uam.phone.token'), the Hands bridge ON, notifications OFF. Idempotent.
"""
import pathlib, sys

mod = pathlib.Path(sys.argv[1])
TOKEN_TS = """const uamToken = (): string => {
  try {
    let t = localStorage.getItem('uam.phone.token');
    if (!t) {
      t = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
      localStorage.setItem('uam.phone.token', t);
    }
    return t;
  } catch {
    return '';
  }
};

"""


def sub(path, old, new, marker):
    p = mod / path
    t = p.read_text(encoding="utf-8")
    if marker in t:
        print(f"already patched: {path} ({marker})")
        return
    if t.count(old) != 1:
        sys.exit(f"patch_module: expected exactly one match in {path} for {old[:50]!r}, found {t.count(old)}")
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"patched: {path} ({marker})")


sub("data/index.ts", "export const NANOMUSE_CONFIG = {\n", TOKEN_TS + "export const NANOMUSE_CONFIG = {\n", "uamToken = ")
sub(
    "data/index.ts",
    "  ...defaults,\n",
    "  ...defaults,\n"
    "  // UAM embed: same-origin server, shared token, Hands on, notifications off\n"
    "  ...(import.meta.env.VITE_NANOMUSE_EMBED\n"
    "    ? { serverUrl: typeof window !== 'undefined' ? window.location.origin : '', token: uamToken(), notify: false, gui: true }\n"
    "    : {}),\n",
    "VITE_NANOMUSE_EMBED",
)
# a browser that visited before has the old (token-less) settings saved: force ours after hydration
sub(
    "state.ts",
    "    afterHydration: () => bridge.sync(),\n",
    "    afterHydration: () => {\n"
    "      if (import.meta.env.VITE_NANOMUSE_EMBED) {\n"
    "        queueMicrotask(() =>\n"
    "          useNanoMuseStore.setState({ serverUrl: NANOMUSE_CONFIG.serverUrl, token: NANOMUSE_CONFIG.token, notify: false, gui: true }),\n"
    "        );\n"
    "      }\n"
    "      bridge.sync();\n"
    "    },\n",
    "queueMicrotask",
)
# the frame loads UAM's chat page (main.py serves it at /?ui=nanomuse)
sub(
    "pages/MusePage.tsx",
    "    url.pathname = '/';\n",
    "    url.pathname = '/';\n"
    "    if (import.meta.env.VITE_NANOMUSE_EMBED) url.searchParams.set('ui', 'nanomuse');\n",
    "VITE_NANOMUSE_EMBED",
)
