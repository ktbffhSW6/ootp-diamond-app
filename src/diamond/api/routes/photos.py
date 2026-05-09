"""Image streaming endpoints — player headshots + team logos.

Endpoints:
- ``GET /api/photos/players/{player_id}.png`` — streams
  ``<save>/news/html/images/person_pictures/player_{player_id}.png``
  if it exists; returns 404 otherwise.
- ``GET /api/photos/teams/{team_id}.png?size=N`` — streams the
  pre-rendered team logo from
  ``<save>/news/html/images/team_logos/<logo_file_name>``. The
  ``logo_file_name`` is read from the warehouse `teams` table; OOTP
  pre-renders 7 size variants per team (16/25/40/50/110/full/small)
  and the route picks the closest match.

OOTP generates faces for in-save players (active rosters + recent
retirees) but does NOT auto-write the PNG to disk on player creation
— the file only lands when the user clicks **"FORCE UPDATE /
GENERATE ALL PLAYER PICTURES"** in OOTP's FaceGen settings. Team
logos, by contrast, are written to disk by OOTP automatically on
save creation/load (no user action required). The frontend handles
missing files gracefully — `PlayerAvatar` falls back to initials,
`TeamLogo` falls back to the abbr or a generic placeholder.

Caching strategy (D24): **revalidation-based, not time-based.** Each
200 response carries ``ETag`` + ``Last-Modified`` headers derived
from the file's mtime + size; subsequent requests send
``If-None-Match`` / ``If-Modified-Since`` and the route returns a
~500-byte 304 when the file hasn't changed. Browser cache lives
indefinitely; updates appear immediately when OOTP rewrites the
file. No artificial TTL — there's no good reason to evict cache
entries on a wall-clock timer when the disk is right there to ask.

404s carry no cache header — local file stats are sub-millisecond
and we want a freshly-rendered image to appear the instant OOTP
finishes its bulk regen, not after a max-age window expires.

Security note: these are **read-only file streamers scoped to single
fixed directories**. Each route validates the integer id before
constructing the path. The team-logo route additionally restricts the
filename to alphanumeric + underscore + dash + dot characters before
any disk lookup — no traversal vector.
"""

from __future__ import annotations

import re
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

import duckdb

from diamond.api.warehouse import get_active_save, get_cursor

router = APIRouter()


_PHOTO_SUBPATH = Path("news") / "html" / "images" / "person_pictures"
_LOGO_SUBPATH = Path("news") / "html" / "images" / "team_logos"

# Allowed filename characters for team logos. OOTP only writes a-z, 0-9,
# underscore, dash, parens, and dot — the regex below is a strict
# allowlist that rejects anything weird before we touch the disk.
_LOGO_FILENAME_RE = re.compile(r"^[A-Za-z0-9_().\-]+\.png$")

# OOTP-pre-rendered size variants. Map a requested pixel size to the
# closest available variant (snapping prevents a half-dozen non-existent
# variants from 404'ing). "" = full-size original.
_LOGO_SIZE_VARIANTS: tuple[int, ...] = (16, 25, 40, 50, 110)


def _resolve_logo_size_suffix(size: int | None) -> str:
    """Map a UI-requested pixel size to OOTP's nearest pre-rendered variant.

    Returns the filename suffix to append before ``.png`` — either ``""``
    for the full-size image (≥ 110px or no size param) or ``_<N>`` for
    one of the variants. Always returns a string the route can
    string-format with the base name.
    """
    if size is None:
        return ""
    # Snap to the nearest pre-rendered size; anything > 110 = full.
    if size > 110:
        return ""
    nearest = min(_LOGO_SIZE_VARIANTS, key=lambda v: abs(v - size))
    return f"_{nearest}"


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


@router.get("/photos/teams/{team_id}.png")
def get_team_logo(
    team_id: int,
    request: Request,
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    size: Annotated[
        int | None,
        Query(description="Requested px (snaps to OOTP variant: 16/25/40/50/110/full)"),
    ] = None,
) -> Response:
    """Stream the team logo PNG with revalidation-based caching.

    Resolves the logo filename via the warehouse's ``teams.logo_file_name``
    column (OOTP writes this on save creation), snaps the size param to
    the nearest pre-rendered variant in
    ``<save>/news/html/images/team_logos/``, and streams with the same
    ETag/Last-Modified revalidation pattern as the player headshot route.
    """
    row = cursor.execute(
        "SELECT logo_file_name FROM teams WHERE team_id = ?",
        [team_id],
    ).fetchone()
    if row is None or not row[0]:
        raise HTTPException(
            status_code=404,
            detail=f"No logo_file_name registered for team_id={team_id}",
        )
    base_filename: str = row[0]

    # Inject the size suffix before the `.png` extension. OOTP's variant
    # naming is e.g. boston_red_sox_50.png (50px) or boston_red_sox.png
    # (full). We slice on the last `.` to handle filenames that contain
    # dots (none observed today, but defensive).
    suffix = _resolve_logo_size_suffix(size)
    if suffix:
        if not base_filename.lower().endswith(".png"):
            raise HTTPException(
                status_code=404,
                detail=f"Unexpected logo filename '{base_filename}'",
            )
        sized_filename = f"{base_filename[:-4]}{suffix}.png"
    else:
        sized_filename = base_filename

    # Strict allowlist on the resolved filename — defense in depth even
    # though the source is the warehouse, not user input.
    if not _LOGO_FILENAME_RE.match(sized_filename):
        raise HTTPException(
            status_code=404,
            detail=f"Logo filename failed allowlist: '{sized_filename}'",
        )

    save = get_active_save()
    logo_path = save.save_dir / _LOGO_SUBPATH / sized_filename

    # Fall back to the full-size variant if the requested size doesn't
    # exist — some teams (especially affiliates / non-MLB orgs) only
    # have a subset of variants. This keeps the picker forgiving without
    # the frontend needing to know which variants are present.
    if not logo_path.is_file() and suffix:
        logo_path = save.save_dir / _LOGO_SUBPATH / base_filename

    if not logo_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No logo file at {logo_path.name}",
        )

    stat = logo_path.stat()
    mtime = stat.st_mtime
    etag = _build_etag(mtime, stat.st_size)
    last_modified_http = formatdate(mtime, usegmt=True)

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
            pass

    return FileResponse(
        logo_path,
        media_type="image/png",
        headers={
            "ETag": etag,
            "Last-Modified": last_modified_http,
            "Cache-Control": "no-cache",
        },
    )
