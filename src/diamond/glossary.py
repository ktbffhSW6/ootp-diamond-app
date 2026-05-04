"""Glossary CLI — terminal + markdown rendering of the stat dictionary.

Validates that the dictionary is well-formed and gives us a queryable
glossary surface before any frontend exists. Per Decision D15, this CLI
is the canonical way to see what a stat means until the `/glossary` web
route lands.

Modes:
  - `diamond glossary`                  — list all entries grouped by category
  - `diamond glossary <id>`             — full detail for one stat
  - `diamond glossary --category <cat>` — filter to one category
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from diamond.dictionary import CATEGORIES, STATS, Stat

console = Console()


def _render_one(stat: Stat) -> None:
    """Render a single stat's full detail to the terminal."""
    console.rule(f"[bold cyan]{stat.display_name}  ({stat.short_label})")
    body = [
        f"**id**: `{stat.id}`",
        f"**category**: {stat.category}",
        f"**units**: {stat.units}",
        "",
        f"_{stat.description}_",
        "",
        f"**Formula**: `{stat.formula_plain}`",
        "",
        f"**Typical range**: {stat.typical_range}",
        "",
        f"**How to read**: {stat.interpretation}",
    ]
    if stat.caveats:
        body.extend(["", f"**Caveats**: {stat.caveats}"])
    body.extend([
        "",
        f"**Source**: `{stat.source}`",
        f"**Formula source**: {stat.formula_source}",
    ])
    if stat.related:
        body.append(f"**Related**: {', '.join(stat.related)}")
    if stat.refs:
        body.append("**External**: " + " · ".join(
            f"[{name}]({url})" for name, url in stat.refs.items()
        ))
    console.print(Markdown("\n".join(body)))


def _render_category_table(category: str) -> None:
    """Render a one-row-per-stat compact table for one category."""
    in_cat = sorted(
        (s for s in STATS.values() if s.category == category),
        key=lambda s: s.id,
    )
    if not in_cat:
        return
    console.rule(f"[bold cyan]Category: {category}  ({len(in_cat)} stats)")
    t = Table(show_header=True, header_style="bold")
    t.add_column("id")
    t.add_column("short")
    t.add_column("name")
    t.add_column("units")
    t.add_column("description", overflow="fold")
    for s in in_cat:
        # First sentence of description for compact display.
        short_desc = s.description.split(".")[0] + "."
        t.add_row(s.id, s.short_label, s.display_name, s.units, short_desc)
    console.print(t)


def _write_markdown(output_path: Path, *, only_category: str | None = None) -> None:
    """Write a full markdown glossary to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md: list[str] = ["# Diamond stat glossary", ""]
    if only_category:
        md.append(f"_Filtered to category: **{only_category}**_")
        md.append("")
    md.append(
        "_Source of truth: `diamond.dictionary.STATS` (Decision D15). "
        "Every column header / chart axis / AI prompt / glossary page "
        "in Diamond reads from this single Python module. Adding or "
        "changing a stat = update the dictionary entry._"
    )
    md.append("")

    cats_to_render = [only_category] if only_category else list(CATEGORIES)
    for cat in cats_to_render:
        in_cat = sorted(
            (s for s in STATS.values() if s.category == cat),
            key=lambda s: s.id,
        )
        if not in_cat:
            continue
        md.append(f"## {cat.capitalize()}")
        md.append("")
        for s in in_cat:
            md.append(f"### {s.display_name}  (`{s.id}`)")
            md.append("")
            md.append(f"**Short label**: `{s.short_label}` · "
                      f"**Units**: {s.units}")
            md.append("")
            md.append(s.description)
            md.append("")
            if s.formula_tex:
                md.append(f"**Formula**:  $${s.formula_tex}$$")
                md.append("")
                md.append(f"_(plain): `{s.formula_plain}`_")
                md.append("")
            else:
                md.append(f"**Formula**: `{s.formula_plain}`")
                md.append("")
            md.append(f"- **Typical range**: {s.typical_range}")
            md.append(f"- **How to read**: {s.interpretation}")
            if s.caveats:
                md.append(f"- **Caveats**: {s.caveats}")
            md.append(f"- **Source**: `{s.source}`")
            md.append(f"- **Formula source**: {s.formula_source}")
            if s.related:
                md.append(f"- **Related**: {', '.join(f'`{r}`' for r in s.related)}")
            if s.refs:
                ref_md = " · ".join(
                    f"[{name}]({url})" for name, url in s.refs.items()
                )
                md.append(f"- **External**: {ref_md}")
            md.append("")
    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Glossary written:[/green] {output_path}")


def run(
    *,
    stat_id: str | None = None,
    category: str | None = None,
    output_path: Path | None = None,
) -> Path | None:
    """Render the glossary.

    Args:
        stat_id: when provided, render full detail for one stat.
        category: when provided, filter to that category.
        output_path: when provided, also write a full markdown file
                     (otherwise terminal-only).
    """
    if stat_id is not None:
        if stat_id not in STATS:
            console.print(
                f"[red]Unknown stat id:[/red] {stat_id!r}\n"
                f"[dim]Try `diamond glossary` to list all entries.[/dim]"
            )
            return None
        _render_one(STATS[stat_id])
        if output_path:
            _write_markdown(output_path)
        return output_path

    if category is not None:
        if category not in CATEGORIES:
            console.print(
                f"[red]Unknown category:[/red] {category!r}\n"
                f"[dim]Valid: {', '.join(CATEGORIES)}[/dim]"
            )
            return None
        _render_category_table(category)
        if output_path:
            _write_markdown(output_path, only_category=category)
        return output_path

    # Default: list every category as a compact table
    console.print(
        f"[bold]Diamond stat glossary[/bold]  "
        f"[dim]({len(STATS)} entries across {len(CATEGORIES)} categories; "
        f"D15 source of truth at `diamond.dictionary.STATS`)[/dim]\n"
    )
    for cat in CATEGORIES:
        _render_category_table(cat)
    if output_path is None:
        output_path = Path("audit_output") / "glossary.md"
    _write_markdown(output_path)
    return output_path
