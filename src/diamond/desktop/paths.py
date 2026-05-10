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
    """Path to ``server.js`` (Next.js standalone entry)."""
    return web_standalone_dir() / "server.js"


def assets_dir() -> Path:
    """Bundled icons / splash HTML / etc.

    Frozen: ``<_MEIPASS>/desktop_assets/``.
    Source: ``<repo>/src/diamond/desktop/assets/``.
    """
    if is_frozen():
        return bundle_root() / "desktop_assets"
    return Path(__file__).resolve().parent / "assets"
