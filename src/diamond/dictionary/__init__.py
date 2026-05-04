"""Stat dictionary — single source of truth for stat metadata.

Per Decision D15: every column header, chart axis label, AI prompt,
and glossary page reads from this module rather than hand-coding
labels and formulas. The dictionary makes definitions data, not
literature, and makes them queryable, versionable, and AI-injectable.

Usage::

    from diamond.dictionary import STATS

    woba = STATS["wOBA"]
    print(woba.display_name)        # "Weighted On-Base Average"
    print(woba.formula_tex)         # KaTeX-renderable LaTeX
    print(woba.refs["Fangraphs"])   # "https://library.fangraphs.com/offense/woba/"

Maintenance contract:
- Adding a new stat = add an entry to ``_stats.py``.
- Changing a formula = update the entry AND the implementing code (the
  ``Stat.source`` field cross-references the implementation; mismatch
  is a code-review smell).
- Any new UI label, chart axis, or AI prompt MUST come from the
  dictionary — no hand-coded labels in feature code.
- Categories are constrained to the values in ``CATEGORIES`` below.

Cohort scope: this is the **thin** v1 dictionary covering ~35 of the
~150 stats Diamond will eventually surface. Entries cover slash-line,
counting batting/pitching, league-relative advanced (wOBA / wRC+ /
OPS+ / ERA+ / FIP / SIERA), Custom WAR (oWAR / pit_WAR), and the
Statcast / save-side EV cohort. Long-tail stats land here as UI
screens reach for them; never lag behind what's exposed.
"""

from __future__ import annotations

from dataclasses import dataclass

# Allowed `Stat.category` values. UI surfaces (glossary filter, chart
# builder dimension picker) consume this list directly. New categories
# require both adding here and any UI consumer that switches on it.
CATEGORIES: tuple[str, ...] = (
    "batting",     # raw batting counting + slash-line stats
    "pitching",    # raw pitching counting + rate stats
    "fielding",    # defensive metrics
    "advanced",    # league-relative or formula-derived (wOBA, FIP, ...)
    "value",       # WAR-family
    "statcast",    # exit-velocity / barrel / hit-distance
    "ratings",     # 20-80 scouting tools (future entries)
)


@dataclass(frozen=True)
class Stat:
    """Canonical metadata for one stat.

    Attributes
    ----------
    id
        Stable internal key, used as ``STATS[id]``. Examples:
        ``"AVG"``, ``"wOBA"``, ``"OPS_plus"``, ``"K_pct_pitcher"``.
        Convention: short_label-shaped, dots replaced with underscores
        (so ``OPS+`` becomes ``OPS_plus``); pitcher/batter homonyms
        get a ``_pitcher`` / ``_batter`` suffix when needed.
    display_name
        Human-readable full name. Example: ``"Weighted On-Base Average"``.
    short_label
        Compact label for dense tables / chart axes. Example: ``"wOBA"``.
    category
        One of ``CATEGORIES``.
    formula_tex
        KaTeX-renderable LaTeX. Empty string when the stat is a raw
        warehouse column with no derivation (e.g., ``HR``).
    formula_plain
        Plain-text formula fallback for terminal output / non-KaTeX
        environments. Mirrors ``formula_tex`` semantically.
    description
        One- to two-sentence summary. The first sentence is the
        glossary tooltip; the second adds context.
    units
        Free-text unit description. Examples: ``"rate (.000-1.000)"``,
        ``"index (100=lg avg)"``, ``"count"``, ``"runs"``, ``"mph"``,
        ``"wins"``, ``"%"``.
    typical_range
        Free-text orientation. Example: ``"MLB stars: .380+; league
        average: ~.315; replacement: ~.290"``. Used by the glossary
        page and AI prompt context.
    interpretation
        How to read the value. Direction (higher / lower better),
        what a 1-unit move means, etc.
    caveats
        Known limitations, calibration notes, or cases where the stat
        misleads. ``None`` if no caveats apply.
    source
        Dotted path to the implementing module/function or the
        warehouse column path that backs this stat. Examples:
        ``"diamond.advanced.sabermetric.woba_per_player"``,
        ``"f_player_season_batting.hr"``.
    formula_source
        Where the formula came from. Examples: ``"Fangraphs standard
        linear weights, park-halved"``, ``"OOTP raw"``.
    related
        IDs of related stats (rendered as cross-links on the glossary
        detail page).
    refs
        External glossary URLs keyed by site name. Example:
        ``{"Fangraphs": "https://...", "Bref": "https://..."}``.
    """

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
    related: tuple[str, ...]
    refs: dict[str, str]

    def __post_init__(self) -> None:
        # Lightweight sanity at instantiation time — we don't lock down
        # `id` / `category` formats with regex, but we do reject the
        # most likely typos in `category`.
        if self.category not in CATEGORIES:
            raise ValueError(
                f"Stat {self.id!r} has unknown category {self.category!r}; "
                f"must be one of {CATEGORIES}"
            )


# Entries live in `_stats.py` for readability; this re-export is the
# canonical import path for consumers.
from diamond.dictionary._stats import STATS  # noqa: E402

__all__ = ["Stat", "CATEGORIES", "STATS"]
