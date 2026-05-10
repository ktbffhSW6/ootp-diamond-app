"""Build the desktop bundle.

Pipeline:

    1. cd web && npm run build           (Next.js standalone output)
    2. Copy web/.next/static  → web/.next/standalone/.next/static
    3. Copy web/public        → web/.next/standalone/public
    4. (optional) PyInstaller → dist/Diamond.exe

Step 4 runs only with ``--package`` (otherwise stops after step 3 so
``python -m diamond.desktop`` can boot from source against the
freshly-built standalone tree).

Why this script exists: ``next build`` with ``output: 'standalone'``
emits a tree that's *almost* self-contained but deliberately omits
``.next/static`` and ``public/`` — the docs say "you should copy
these manually". This script does that copy step plus invokes
PyInstaller with our spec file.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
STANDALONE = WEB_DIR / ".next" / "standalone"
SPEC_FILE = REPO_ROOT / "src" / "diamond" / "desktop" / "diamond.spec"


def _run(cmd: list[str], *, cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}  (cwd={cwd})", flush=True)
    subprocess.check_call(cmd, cwd=str(cwd))


def _npm() -> str:
    """Resolve npm executable — Windows installs it as npm.cmd."""
    return "npm.cmd" if sys.platform == "win32" else "npm"


def build_next() -> None:
    """Run `npm run build` against ``web/``."""
    if not WEB_DIR.exists():
        raise FileNotFoundError(f"web/ not found at {WEB_DIR}")
    _run([_npm(), "run", "build"], cwd=WEB_DIR)


def copy_static_assets() -> None:
    """Replicate Next's static + public dirs into the standalone tree.

    Idempotent — clears the destination first, then copies.
    """
    if not STANDALONE.exists():
        raise FileNotFoundError(
            f"Standalone build not found at {STANDALONE}. Did `next build` run? "
            "Confirm `output: 'standalone'` is set in next.config.mjs."
        )

    static_src = WEB_DIR / ".next" / "static"
    static_dst = STANDALONE / ".next" / "static"
    if static_src.exists():
        if static_dst.exists():
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)
        print(f"  copied {static_src.relative_to(REPO_ROOT)} → {static_dst.relative_to(REPO_ROOT)}")

    public_src = WEB_DIR / "public"
    public_dst = STANDALONE / "public"
    if public_src.exists():
        if public_dst.exists():
            shutil.rmtree(public_dst)
        shutil.copytree(public_src, public_dst)
        print(f"  copied {public_src.relative_to(REPO_ROOT)} → {public_dst.relative_to(REPO_ROOT)}")


def package_pyinstaller() -> None:
    """Invoke PyInstaller with the desktop spec."""
    if not SPEC_FILE.exists():
        raise FileNotFoundError(f"PyInstaller spec not found at {SPEC_FILE}")
    _run(["pyinstaller", "--noconfirm", str(SPEC_FILE)], cwd=REPO_ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Diamond desktop bundle.")
    parser.add_argument(
        "--skip-next",
        action="store_true",
        help="Skip `next build` (use the existing .next/standalone tree).",
    )
    parser.add_argument(
        "--package",
        action="store_true",
        help="Also run PyInstaller to produce dist/Diamond.exe.",
    )
    args = parser.parse_args(argv)

    if not args.skip_next:
        build_next()
    copy_static_assets()
    if args.package:
        package_pyinstaller()
        print("\nDiamond.exe → dist/Diamond/Diamond.exe")
    else:
        print(
            "\nReady to launch from source: "
            "`python -m diamond.desktop`  (no --package was passed)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
