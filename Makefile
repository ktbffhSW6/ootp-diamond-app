# Diamond dev workflow — see docs/DEV.md for the full guide.
#
# Common tasks:
#   make api      — run the FastAPI backend on :8000
#   make web      — run the Next.js frontend on :3000
#   make types    — regenerate web/lib/types/api.ts from Pydantic schemas
#   make smoke    — run scripts/smoke_warehouse.py
#   make help     — list all targets
#
# Note: there's no `make dev` that runs both servers in parallel —
# parallel-make on Windows is fragile, and you almost always want the
# two processes in separate terminals anyway so you can see each one's
# logs cleanly. Open two terminals: `make api` in one, `make web` in
# the other.

.PHONY: help api web types smoke install-dev install-desktop desktop desktop-package clean

PY := .venv/Scripts/python.exe

help:
	@echo "Diamond — common tasks:"
	@echo "  make api       Run FastAPI backend on http://localhost:8000"
	@echo "  make web       Run Next.js frontend on http://localhost:3000"
	@echo "  make types     Regenerate web/lib/types/api.ts from Pydantic"
	@echo "  make smoke     Run end-to-end warehouse smoke test"
	@echo "  make install-dev   Install Python dev deps (one-time)"
	@echo ""
	@echo "First-time setup: see docs/DEV.md"

api:
	$(PY) -m uvicorn diamond.api:app --reload --host 127.0.0.1 --port 8000

web:
	cd web && pnpm dev

types:
	$(PY) scripts/generate_types.py

smoke:
	$(PY) scripts/smoke_warehouse.py

install-dev:
	$(PY) -m pip install -e ".[dev]"

# Desktop shell (D32)
install-desktop:
	$(PY) -m pip install -e ".[desktop]"

# Build standalone Next.js + boot the native window from source.
desktop:
	$(PY) scripts/build_desktop.py
	$(PY) -m diamond.desktop

# Full bundle: standalone + PyInstaller → dist/Diamond/Diamond.exe.
desktop-package:
	$(PY) scripts/build_desktop.py --package

clean:
	rm -rf web/.next web/node_modules/.cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
