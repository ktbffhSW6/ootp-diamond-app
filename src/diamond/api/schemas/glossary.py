"""Glossary endpoint Pydantic schemas.

Wire-shape mirror of ``diamond.dictionary.Stat``. Kept as a separate
class (rather than re-exporting the dataclass) so:

- The API contract is pinned and explicit — adding a field to ``Stat``
  doesn't silently leak into the API.
- Pydantic-side validation runs on serialization (catches typos in
  newly-added fields).
- ``pydantic-to-typescript`` reads from this module directly to
  generate the TS interface.

Pydantic v2 + ``frozen=True`` model_config keeps the response
immutable on the Python side; TS receives plain JSON either way.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GlossaryEntry(BaseModel):
    """One stat dictionary entry, serialized for HTTP.

    Field-for-field mirror of :class:`diamond.dictionary.Stat`. See
    ``src/diamond/dictionary/__init__.py`` for the canonical
    descriptions of each field.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    short_label: str
    category: str
    formula_tex: str
    formula_plain: str
    description: str
    units: str
    typical_range: str
    interpretation: str
    caveats: str | None
    source: str
    formula_source: str
    related: list[str]
    refs: dict[str, str]


class GlossaryListResponse(BaseModel):
    """``GET /api/glossary`` envelope.

    Carries the full entry list plus the canonical category ordering
    (so the frontend doesn't have to maintain a parallel CATEGORIES
    constant). ``count`` is convenience for the client.
    """

    model_config = ConfigDict(frozen=True)

    entries: list[GlossaryEntry]
    categories: list[str]
    count: int
