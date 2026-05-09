"""Player headshot endpoint — streams the OOTP-generated face image
from the active save's photo directory.

Endpoint:
- ``GET /api/photos/players/{player_id}.png`` — streams
  ``<save>/news/html/images/person_pictures/player_{player_id}.png``
  if it exists; returns 404 otherwise.

OOTP generates faces for in-save players (active rosters + recent
retirees) but does NOT auto-write the PNG to disk on player creation
— the file only lands when the user clicks **"FORCE UPDATE /
GENERATE ALL PLAYER PICTURES"** in OOTP's FaceGen settings. The
frontend handles missing-photo gracefully via ``components/
PlayerAvatar.tsx``'s onError → initials fallback.

Caching strategy (D24): **revalidation-based, not time-based.** Each
200 response carries ``ETag`` + ``Last-Modified`` headers derived
from the file's mtime + size; subsequent requests send
``If-None-Match`` / ``If-Modified-Since`` and the route returns a
~500-byte 304 when the file hasn't changed. Browser cache lives
indefinitely; updates appear immediately when OOTP rewrites the
PNG. No artificial TTL — there's no good reason to evict cache
entries on a wall-clock timer when the disk is right there to ask.

404s carry no cache header — local file stats are sub-millisecond
and we want a freshly-rendered photo to appear the instant OOTP
finishes its bulk regen, not after a max-age window expires.

Security note: this is a **read-only file streamer scoped to a single
fixed directory** — the route validates `player_id` is an integer
before constructing the path, so there's no traversal vector.
"""

from __future__ import annotations

from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from diamond.api.warehouse import get_active_save

router = APIRouter()


_PHOTO_SUBPATH = Path("news") / "html" / "images" / "person_pictures"


def _build_etag(mtime: float, size: int) -> str:
    """Stable identity for one (file-version) tuple.

    `mtime` granularity on Windows is 100 ns, but for our purposes
    second-precision is plenty — OOTP regenerates the file rather
    than mutating in place, so any change bumps both the mtime and
    typically the size. Quoted per RFC 7232.
    """
    return f'"{int(mtime)}-{size}"'


@router.get("/photos/players/{player_id}.png")
def get_player_photo(player_id: int, request: Request) -> Response:
    """Stream the player headshot PNG with revalidation-based caching.

    On a fresh fetch returns 200 + the file bytes + ETag + Last-Modified.
    On revalidation (browser sends If-None-Match / If-Modified-Since)
    returns 304 with the same validators if the file hasn't changed
    on disk; otherwise returns 200 with the new bytes.

    Cache-Control is ``no-cache`` (always revalidate, never serve
    stale) — paired with the cheap 304 path this gives us "cache
    forever + instant invalidation when OOTP regenerates" without
    the user ever needing to hard-refresh.
    """
    save = get_active_save()
    photo_path = save.save_dir / _PHOTO_SUBPATH / f"player_{player_id}.png"

    if not photo_path.is_file():
        # No cache header. Local stat is microseconds; if a regen lands
        # five seconds from now we want the next page-load to pick up
        # the new photo without a TTL barrier.
        raise HTTPException(
            status_code=404,
            detail=f"No headshot for player_id={player_id}",
        )

    stat = photo_path.stat()
    mtime = stat.st_mtime
    etag = _build_etag(mtime, stat.st_size)
    last_modified_http = formatdate(mtime, usegmt=True)

    # ── Revalidation: ETag wins over If-Modified-Since when both arrive,
    #     per RFC 7232 §6 (precedence). Either path returns 304 with the
    #     validators echoed; the browser keeps using its cached body.
    client_etag = request.headers.get("if-none-match")
    if client_etag and client_etag == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Last-Modified": last_modified_http,
                "Cache-Control": "no-cache",
            },
        )

    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            client_dt = parsedate_to_datetime(if_modified_since)
            if client_dt is not None and int(client_dt.timestamp()) >= int(mtime):
                return Response(
                    status_code=304,
                    headers={
                        "ETag": etag,
                        "Last-Modified": last_modified_http,
                        "Cache-Control": "no-cache",
                    },
                )
        except (TypeError, ValueError):
            # Malformed header — fall through to a full 200 response.
            pass

    return FileResponse(
        photo_path,
        media_type="image/png",
        headers={
            "ETag": etag,
            "Last-Modified": last_modified_http,
            # `no-cache` = always revalidate before reusing cached
            # bytes. Combined with the cheap 304 path above, this is
            # "cache forever, auto-refresh on file change."
            "Cache-Control": "no-cache",
        },
    )
