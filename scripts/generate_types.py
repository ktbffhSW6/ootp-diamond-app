"""Regenerate `web/lib/types/api.ts` from the Pydantic schemas.

Per Decision D16: Pydantic models in `src/diamond/api/schemas/` are
the single source of truth for the API contract. This script runs
``pydantic-to-typescript`` over that package and writes the result to
``web/lib/types/api.ts``, which the frontend imports.

Requirements:
  - pydantic-to-typescript (Python; in `[dev]` extras)
  - json2ts CLI (Node; installed via `pnpm install` in `web/`)
    json2ts is the json-schema → TS bridge that pydantic-to-typescript
    shells out to. Without it, this script will fail with a
    user-friendly error.

Run manually:
    python scripts/generate_types.py

Or via the make target:
    make types
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so unicode arrows in our print
# statements don't trip cp1252. Same workaround used in
# `src/diamond/cli.py` and `scripts/smoke_warehouse.py`.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Locate paths relative to repo root (this script's parent's parent).
REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_PACKAGE = "diamond.api.schemas"
OUT_PATH = REPO_ROOT / "web" / "lib" / "types" / "api.ts"


def _find_json2ts() -> Path | None:
    """Look for the json2ts CLI on PATH and in `web/node_modules`.

    The library calls it as a subprocess. On Windows, the binary
    typically lands in `web/node_modules/.bin/json2ts.cmd`.
    """
    found = shutil.which("json2ts")
    if found:
        return Path(found)
    # Fall back to the project-local install.
    candidates = [
        REPO_ROOT / "web" / "node_modules" / ".bin" / "json2ts",
        REPO_ROOT / "web" / "node_modules" / ".bin" / "json2ts.cmd",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> int:
    json2ts = _find_json2ts()
    if json2ts is None:
        print(
            "ERROR: json2ts CLI not found. It comes from the "
            "json-schema-to-typescript npm package, which "
            "pydantic-to-typescript shells out to.\n\n"
            "Fix: install Node 20+ and pnpm, then:\n"
            "  cd web && pnpm install\n\n"
            "That installs json-schema-to-typescript locally; this "
            "script picks it up from `web/node_modules/.bin/`.",
            file=sys.stderr,
        )
        return 1

    # pydantic-to-typescript expects to find json2ts on PATH; if it's
    # only in web/node_modules/.bin, prepend that to PATH for this run.
    bin_dir = str(json2ts.parent)
    env_path = os.environ.get("PATH", "")
    if bin_dir not in env_path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + env_path

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Import here so the import-error message above is more specific
    # if pydantic-to-typescript itself isn't installed.
    from pydantic2ts import generate_typescript_defs

    print(f"→ generating TS from {SCHEMAS_PACKAGE} → {OUT_PATH}")
    generate_typescript_defs(
        SCHEMAS_PACKAGE,
        str(OUT_PATH),
        json2ts_cmd=str(json2ts),
    )

    # Prepend a header so consumers know not to hand-edit. The library
    # writes a minimal header on its own; we add a Diamond-specific
    # pointer back at D16.
    body = OUT_PATH.read_text(encoding="utf-8")
    header = (
        "// AUTO-GENERATED FROM PYDANTIC SCHEMAS — DO NOT EDIT BY HAND.\n"
        "// Source of truth: src/diamond/api/schemas/ (Pydantic v2 models)\n"
        "// Regenerate via: make types  (or python scripts/generate_types.py)\n"
        "// See docs/DECISIONS.md D16 for the type-gen pipeline contract.\n\n"
    )
    if not body.lstrip().startswith("// AUTO-GENERATED"):
        OUT_PATH.write_text(header + body, encoding="utf-8")

    print(f"✓ wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
