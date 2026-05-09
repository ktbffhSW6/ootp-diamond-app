"""Player headshot endpoint — streams the OOTP-generated face image
from the active save's photo directory.

Endpoint:
- ``GET /api/photos/players/{player_id}.png`` — streams
  ``<save>/news/html/images/person_pictures/player_{player_id}.png``
  if it exists; returns 404 otherwise.

OOTP generates faces for in-save players (active rosters + recent
retirees) but does NOT generate them for every imported real-history
player — Bonds, Mantle, etc. typically don't have photo files. The
frontend handles this with a per-image ``onError`` fallback to an
initials avatar (see ``components/PlayerAvatar.tsx``); the API just
honestly returns 404 for missing files.

Why the route exists at all: the photos live OUTSIDE the Next.js
``public/`` directory (in the user's OOTP save folder, which moves
per-save), so we can't statically serve them. A thin FastAPI
streamer is the cleanest way to bridge.

Security note: this is a **read-only file streamer scoped to a single
fixed directory** — the route validates `player_id` is an integer
before constructing the path, so there's no traversal vector.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from diamond.api.warehouse import get_active_save

router = APIRouter()


_PHOTO_SUBPATH = Path("news") / "html" / "images" / "person_pictures"


@router.get("/photos/players/{player_id}.png")
def get_player_photo(player_id: int) -> Response:
    """Stream the player headshot PNG, or 404 if missing.

    Cached aggressively — photos rarely change for a given save +
    player_id, and the 404 path is also stable (OOTP doesn't
    retroactively generate faces for missing players). One-day TTL
    is plenty for the local-first use case; the user can hard-refresh
    if a face does appear.
    """
    save = get_active_save()
    photo_path = (
        save.save_dir / _PHOTO_SUBPATH / f"player_{player_id}.png"
    )
    if not photo_path.is_file():
        # Use 404 with a Cache-Control header so the browser remembers
        # this player has no face — saves a follow-up request when
        # the user revisits the player page.
        raise HTTPException(
            status_code=404,
            detail=f"No headshot for player_id={player_id}",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    return FileResponse(
        photo_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )
