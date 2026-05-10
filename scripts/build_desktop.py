"""Build the desktop bundle.

Pipeline:

    1. cd web && npm run build           (Next.js standalone output)
    2. Copy web/.next/static  -> web/.next/standalone/.next/static
    3. Copy web/public        -> web/.next/standalone/public
    4. (optional) PyInstaller -> dist/Diamond.exe

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
    """Run `npm run build` against ``web/``.

    On Windows with pnpm, `next build` may exit non-zero at the
    "Collecting build traces" step (it tries to create symlinks for
    the standalone tree and Windows blocks them without Developer
    Mode). The regular `.next/` build is complete by that point;
    only the standalone tree is partial. The launcher's `next start`
    fallback handles this case gracefully — so we treat a non-zero
    exit as non-fatal IFF `.next/BUILD_ID` exists.
    """
    if not WEB_DIR.exists():
        raise FileNotFoundError(f"web/ not found at {WEB_DIR}")
    print(f"\n$ {_npm()} run build  (cwd={WEB_DIR})", flush=True)
    rc = subprocess.call([_npm(), "run", "build"], cwd=str(WEB_DIR))
    if rc == 0:
        return
    build_id = WEB_DIR / ".next" / "BUILD_ID"
    if build_id.exists():
        print(
            "\n  next build returned non-zero, but .next/BUILD_ID exists. "
            "This is the Windows + pnpm + standalone-symlink quirk; the "
            "regular build is complete and the launcher will use the "
            "`next start` fallback. Continuing.",
            flush=True,
        )
        return
    raise SystemExit(
        "next build failed and .next/BUILD_ID is missing. "
        "Inspect the output above for the actual error."
    )


def copy_static_assets() -> None:
    """Replicate Next's static + public dirs into the standalone tree.

    Idempotent — clears the destination first, then copies.

    No-op if the standalone tree wasn't produced (Windows + pnpm
    symlink case). The launcher's `next start` fallback doesn't
    need this step.
    """
    server_js = STANDALONE / "server.js"
    if not STANDALONE.exists() or not server_js.exists():
        print(
            "  skipping static-asset copy -- standalone tree incomplete. "
            "Launcher will use `next start` fallback.",
            flush=True,
        )
        return

    static_src = WEB_DIR / ".next" / "static"
    static_dst = STANDALONE / ".next" / "static"
    if static_src.exists():
        if static_dst.exists():
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)
        print(f"  copied {static_src.relative_to(REPO_ROOT)} -> {static_dst.relative_to(REPO_ROOT)}")

    public_src = WEB_DIR / "public"
    public_dst = STANDALONE / "public"
    if public_src.exists():
        if public_dst.exists():
            shutil.rmtree(public_dst)
        shutil.copytree(public_src, public_dst)
        print(f"  copied {public_src.relative_to(REPO_ROOT)} -> {public_dst.relative_to(REPO_ROOT)}")


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
        print("\nDiamond.exe -> dist/Diamond/Diamond.exe")
    else:
        print(
            "\nReady to launch from source: "
            "`python -m diamond.desktop`  (no --package was passed)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
