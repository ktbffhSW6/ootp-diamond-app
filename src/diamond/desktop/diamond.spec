# PyInstaller spec for Diamond.exe (D32 desktop shell).
#
# Produces a one-folder bundle at dist/Diamond/ with Diamond.exe at
# the root. We bundle:
#
#   - The diamond Python package (sources + entry point).
#   - The Next.js standalone tree at <bundle>/web_standalone/.
#   - Desktop assets (splash HTML, tray icon) at <bundle>/desktop_assets/.
#
# We deliberately use a one-folder build (not --onefile) because:
#   - Cold-start is faster (no per-launch unpack to TEMP).
#   - The Next.js standalone tree contains thousands of small files;
#     unpacking them every launch would add 2-3s.
#   - Antivirus scanners are friendlier to one-folder bundles.
#
# The user gets a single Start Menu shortcut to dist/Diamond/Diamond.exe;
# the surrounding folder is an implementation detail. An installer
# (Inno Setup / MSIX) wraps it for distribution — not in scope here.
#
# Run via:
#   python scripts/build_desktop.py --package
#
# or:
#   pyinstaller --noconfirm src/diamond/desktop/diamond.spec
#
# Requires the standalone tree at web/.next/standalone/ to already exist
# (build_desktop.py runs `next build` first).

# ruff: noqa
# pylint: skip-file

import sys
from pathlib import Path

# The spec file is loaded by PyInstaller as a script; SPEC_ROOT becomes
# the repo root because PyInstaller cwds to wherever the spec lives.
SPEC_ROOT = Path(SPECPATH).resolve().parents[3]  # src/diamond/desktop → repo root
WEB_STANDALONE = SPEC_ROOT / "web" / ".next" / "standalone"
ASSETS_SRC = SPEC_ROOT / "src" / "diamond" / "desktop" / "assets"

if not WEB_STANDALONE.exists():
    raise SystemExit(
        f"Next.js standalone tree missing at {WEB_STANDALONE}.\n"
        "Run `python scripts/build_desktop.py` first (it will build "
        "and copy assets in)."
    )

# Datas: (source_path_glob, destination_dir_in_bundle).
datas = [
    (str(WEB_STANDALONE), "web_standalone"),
]
if ASSETS_SRC.exists():
    datas.append((str(ASSETS_SRC), "desktop_assets"))

# Hidden imports — Pydantic v2 + uvicorn lifespans + httpx pull a
# few transitive deps that PyInstaller can miss without help.
hiddenimports = [
    "diamond.api.app",
    "diamond.api.routes.health",
    "diamond.api.routes.save",
    "diamond.api.routes.cockpit",
    "diamond.api.routes.glossary",
    "diamond.api.routes.players",
    "diamond.api.routes.roster",
    "diamond.api.routes.movements",
    "diamond.api.routes.standings",
    "diamond.api.routes.records",
    "diamond.api.routes.awards",
    "diamond.api.routes.hof",
    "diamond.api.routes.streaks",
    "diamond.api.routes.draft",
    "diamond.api.routes.pressure",
    "diamond.api.routes.compare",
    "diamond.api.routes.leaderboards",
    "diamond.api.routes.chart_builder",
    "diamond.api.routes.parks",
    "diamond.api.routes.batted_balls",
    "diamond.api.routes.saves",
    "diamond.api.routes.ai",
    "diamond.api.routes.photos",
    "diamond.api.routes.admin",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pywebview backends — bundle the Win32 / Edge Chromium one.
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    # pystray backend (Windows-specific impl chosen at import time).
    "pystray._win32",
    # PIL submodules pystray uses for the tray bitmap.
    "PIL.Image",
    "PIL.ImageDraw",
    # ctypes Win32 wrappers we use in single_instance / win_jobobject.
    "ctypes.wintypes",
]

block_cipher = None

a = Analysis(
    [str(SPEC_ROOT / "src" / "diamond" / "desktop" / "launcher.py")],
    pathex=[str(SPEC_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Big transitive deps we don't actually use at runtime.
        "matplotlib",
        "pandas.tests",
        "numpy.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Diamond",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX trips Windows SmartScreen / AV; not worth the size win.
    console=False,         # Windowed app — no console window ever.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS_SRC / "diamond.ico") if (ASSETS_SRC / "diamond.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Diamond",
)
