"""Glossary endpoint — exposes the D15 stat dictionary over HTTP.

This is intentionally the FIRST real route. It's the cheapest end-to-
end pipeline test: the dictionary is a pure-Python dict, no warehouse
queries, no external services. If `GET /api/glossary` returns valid
JSON and the Next.js frontend can render it, the full backend ↔
frontend ↔ type-gen loop is working.

Endpoints:
- ``GET /api/glossary``        list all entries
- ``GET /api/glossary/{id}``   single entry by id
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from diamond.api.schemas import GlossaryEntry, GlossaryListResponse
from diamond.dictionary import CATEGORIES, STATS

router = APIRouter()


def _stat_to_entry(stat) -> GlossaryEntry:  # noqa: ANN001 (Stat is a frozen dataclass)
    """Convert the dataclass `Stat` to the wire-shape Pydantic model.

    Kept as a single helper so any field added to `Stat` shows up as
    a missing-arg type error here — keeps the API contract honest.
    Cast `related` to a list since the dataclass uses tuple.
    """
    return GlossaryEntry(
        id=stat.id,
        display_name=stat.display_name,
        short_label=stat.short_label,
        category=stat.category,
        formula_tex=stat.formula_tex,
        formula_plain=stat.formula_plain,
        description=stat.description,
        units=stat.units,
        typical_range=stat.typical_range,
        interpretation=stat.interpretation,
        caveats=stat.caveats,
        source=stat.source,
        formula_source=stat.formula_source,
        related=list(stat.related),
        refs=dict(stat.refs),
    )


@router.get("/glossary", response_model=GlossaryListResponse)
def list_glossary() -> GlossaryListResponse:
    """Return every dictionary entry plus the canonical category list.

    Ordering: entries are returned in dictionary-insertion order
    (matches the source-of-truth declaration order in `_stats.py`,
    which is grouped-by-category for readability). The frontend can
    re-sort as needed.
    """
    entries = [_stat_to_entry(s) for s in STATS.values()]
    return GlossaryListResponse(
        entries=entries,
        categories=list(CATEGORIES),
        count=len(entries),
    )


@router.get("/glossary/{stat_id}", response_model=GlossaryEntry)
def get_glossary_entry(stat_id: str) -> GlossaryEntry:
    """Look up a single entry by id. 404 if unknown.

    Note that `stat_id` is case-sensitive — `wOBA` and `WOBA` are
    different. The dictionary uses the conventional public-stats
    capitalization (e.g., `wOBA`, `OPS_plus`), and we don't
    normalize, since accidental case mismatches surface as obvious
    404s rather than silent miss-matches.
    """
    stat = STATS.get(stat_id)
    if stat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown stat id: {stat_id!r}. "
            f"See GET /api/glossary for the catalog.",
        )
    return _stat_to_entry(stat)
