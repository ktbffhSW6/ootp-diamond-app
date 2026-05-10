"""Filesystem layout for the desktop shell.

Two run modes:

- **Source mode** — ``python -m diamond.desktop`` from a checkout.
  Resolves paths relative to the repo root (``src/`` is the package
  parent's parent's parent — see ``REPO_ROOT`` below). Next.js
  standalone build is expected at ``web/.next/standalone/``.

- **Frozen mode** — bundled ``Diamond.exe`` produced by PyInstaller.
  ``sys.frozen`` is set; ``sys._MEIPASS`` points at the unpack dir
  containing both the Python tree and the bundled Next.js standalone
  output (added via the spec file's ``datas``).

Callers use the module-level helpers and don't think about which mode
they're in.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller-built executable."""
    return getattr(sys, "frozen", False)


def bundle_root() -> Path:
    """Root of the runtime tree.

    Frozen: PyInstaller's unpack dir (``sys._MEIPASS``).
    Source: repo root (parent of ``src/``).
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
    # __file__ = .../src/diamond/desktop/paths.py → parents[3] = repo root
    return Path(__file__).resolve().parents[3]


def web_standalone_dir() -> Path:
    """Directory containing the Next.js standalone ``server.js``.

    Frozen: ``<_MEIPASS>/web_standalone/`` (placed by the spec file).
    Source: ``<repo>/web/.next/standalone/``.
    """
    if is_frozen():
        return bundle_root() / "web_standalone"
    return bundle_root() / "web" / ".next" / "standalone"


def web_static_dir() -> Path:
    """Directory containing Next.js static assets.

    Next.js standalone output requires ``.next/static`` and ``public/``
    to be copied alongside ``server.js`` — they're not auto-bundled.
    """
    if is_frozen():
        return bundle_root() / "web_standalone"
    return bundle_root() / "web"


def web_server_entry() -> Path:
    """Path to ``server.js`` (Next.js standalone entry).

    Only valid when the standalone tree exists (post `next build`
    with `output: 'standalone'` AND the post-build asset copy AND —
    on Windows — symlink permissions). Use `web_standalone_ok()` to
    check before assuming this path is live.
    """
    return web_standalone_dir() / "server.js"


def web_standalone_ok() -> bool:
    """True iff the standalone tree is fully usable.

    On Windows + pnpm, `next build` with `output: 'standalone'` can
    succeed at building `.next/` but fail to populate the standalone
    tree's `node_modules` (symlink permissions). When that happens we
    fall back to `next start` against the regular `.next/` build.
    """
    server_js = web_server_entry()
    if not server_js.exists():
        return False
    # The standalone tree should also have a populated node_modules.
    nm = web_standalone_dir() / "node_modules"
    return nm.exists() and any(nm.iterdir())


def web_repo_dir() -> Path:
    """Directory containing ``package.json`` and ``node_modules`` —
    used for the `next start` fallback path."""
    if is_frozen():
        # Frozen builds always use the standalone tree; this is only
        # exercised in source mode.
        return bundle_root() / "web"
    return bundle_root() / "web"


def web_next_bin() -> Path:
    """Path to the next.js CLI script for `next start` invocation.

    `node node_modules/next/dist/bin/next start` is deterministic
    across npm/pnpm/yarn — no shell, no batch wrapper, no PATH
    lookup. Subprocess can use CREATE_NO_WINDOW cleanly.
    """
    return web_repo_dir() / "node_modules" / "next" / "dist" / "bin" / "next"


def assets_dir() -> Path:
    """Bundled icons / splash HTML / etc.

    Frozen: ``<_MEIPASS>/desktop_assets/``.
    Source: ``<repo>/src/diamond/desktop/assets/``.
    """
    if is_frozen():
        return bundle_root() / "desktop_assets"
    return Path(__file__).resolve().parent / "assets"
