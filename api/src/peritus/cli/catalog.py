"""``peritus catalog`` — curate the public expert catalog.

The founder has to hand-build and publish 10–20 catalog experts, so this is
built for bulk work first and one-off tweaks second:

    peritus catalog list                       # what's on the shelf
    peritus catalog publish stoicism --blurb "..." --category Philosophy
    peritus catalog set stoicism --tag ethics --tag virtue --rank 10
    peritus catalog feature stoicism
    peritus catalog unpublish stoicism

    peritus catalog export catalog.json        # dump every expert's curation
    $EDITOR catalog.json                       # edit the whole shelf at once
    peritus catalog apply catalog.json         # push it back, with a diff first
    peritus catalog reorder stoicism kant hume # set rank 1..N in one go

``export``/``apply`` is the bulk path: the file is the whole shelf, editing it
in one pass is far less error-prone than twenty invocations, and ``apply`` shows
a diff and asks before writing.

This talks to Postgres directly (like the rest of the Python CLI), so it is an
operator tool that assumes DB access — not a client of the HTTP API.
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from peritus.cli.display import console, print_error, print_success
from peritus.experts.domain import BLURB_MAX_CHARS, Expert, ExpertVisibility
from peritus.experts.repository import ExpertRepository
from peritus.infrastructure.database import get_pool, init_pool

app = typer.Typer(help="Curate the public expert catalog.")


async def _repo() -> ExpertRepository:
    await init_pool()
    return ExpertRepository(get_pool())


def _run(coro):
    return asyncio.run(coro)


async def _resolve(repo: ExpertRepository, slug: str) -> Expert:
    expert = await repo.get_by_name(slug)
    if expert is None:
        expert = await repo.fuzzy_find(slug)
    if expert is None:
        print_error(f"No expert found matching {slug!r}")
        raise typer.Exit(1)
    return expert


def _validate_blurb(blurb: str | None) -> None:
    if blurb is not None and len(blurb) > BLURB_MAX_CHARS:
        print_error(f"Blurb is {len(blurb)} chars; the limit is {BLURB_MAX_CHARS}.")
        raise typer.Exit(1)


def _curation_of(e: Expert) -> dict[str, Any]:
    c = e.catalog
    return {
        "name": e.name,
        "visibility": c.visibility.value,
        "featured": c.is_featured,
        "rank": c.catalog_rank,
        "blurb": c.blurb,
        "category": c.category,
        "tags": list(c.tags),
    }


def _readiness_note(e: Expert) -> str:
    if e.readiness == "graph_ready":
        return ""
    if e.readiness == "chat_ready":
        return "  [yellow](chat-ready; graph still building)[/yellow]"
    return "  [red](not answerable yet — it will not appear in the catalog)[/red]"


# ── inspection ──────────────────────────────────────────────────────────────


@app.command("list")
def list_catalog(
    all_experts: Annotated[
        bool, typer.Option("--all", help="Include private/unlisted experts too")
    ] = False,
) -> None:
    """Show the catalog in shelf order (featured, then rank, then newest)."""

    async def _inner() -> None:
        repo = await _repo()
        if all_experts:
            experts = await repo.list_all()
        else:
            experts = await repo.list_catalog(limit=100)
        if not experts:
            console.print(
                "[dim]Catalog is empty. Publish one with "
                "[bold]peritus catalog publish <slug>[/bold].[/dim]"
            )
            return
        for e in experts:
            c = e.catalog
            star = "[yellow]*[/yellow]" if c.is_featured else " "
            rank = f"#{c.catalog_rank}" if c.catalog_rank is not None else "—"
            vis = c.visibility.value
            colour = {"public": "green", "unlisted": "cyan"}.get(vis, "dim")
            console.print(
                f"{star} [bold]{e.name}[/bold]  [{colour}]{vis}[/{colour}]  "
                f"[dim]{rank}  {c.category or 'uncategorised'}[/dim]"
                f"{_readiness_note(e)}"
            )
            if c.blurb:
                console.print(f"    [dim]{c.blurb}[/dim]")
            if c.tags:
                console.print(f"    [dim]tags: {', '.join(c.tags)}[/dim]")

    _run(_inner())


# ── single-expert curation ──────────────────────────────────────────────────


@app.command("publish")
def publish(
    slug: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
    blurb: Annotated[str | None, typer.Option("--blurb", "-b")] = None,
    category: Annotated[str | None, typer.Option("--category", "-c")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Repeatable")] = None,
    rank: Annotated[int | None, typer.Option("--rank", "-r")] = None,
    featured: Annotated[bool, typer.Option("--featured/--not-featured")] = False,
    unlisted: Annotated[
        bool, typer.Option("--unlisted", help="Shareable by link, but not listed")
    ] = False,
) -> None:
    """Make an expert readable and chattable by anyone."""
    _validate_blurb(blurb)

    async def _inner() -> None:
        repo = await _repo()
        expert = await _resolve(repo, slug)
        visibility = ExpertVisibility.UNLISTED if unlisted else ExpertVisibility.PUBLIC
        updated = await repo.update_catalog(
            expert.id,
            visibility=visibility,
            is_featured=featured or None,
            catalog_rank=rank,
            blurb=blurb,
            category=category,
            tags=list(tag) if tag else None,
        )
        assert updated is not None
        print_success(f"{updated.name} is now {visibility.value}")
        if updated.readiness == "pending":
            console.print(
                "[yellow]Note:[/yellow] this expert has no retrievable corpus yet, so it "
                "will stay out of the catalog until its build reaches chat-ready."
            )
        if visibility is ExpertVisibility.PUBLIC and not updated.catalog.blurb:
            console.print(
                "[dim]Tip: add a blurb — it is the line that sells the card.[/dim]"
            )

    _run(_inner())


@app.command("unpublish")
def unpublish(
    slug: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
) -> None:
    """Take an expert off the shelf (back to private). Curation fields are kept."""

    async def _inner() -> None:
        repo = await _repo()
        expert = await _resolve(repo, slug)
        updated = await repo.update_catalog(
            expert.id, visibility=ExpertVisibility.PRIVATE, is_featured=False
        )
        assert updated is not None
        print_success(f"{updated.name} is now private")

    _run(_inner())


@app.command("set")
def set_fields(
    slug: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
    blurb: Annotated[str | None, typer.Option("--blurb", "-b")] = None,
    category: Annotated[str | None, typer.Option("--category", "-c")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Repeatable")] = None,
    rank: Annotated[int | None, typer.Option("--rank", "-r")] = None,
    clear: Annotated[
        list[str] | None,
        typer.Option("--clear", help="Field to null out: blurb|category|catalog_rank"),
    ] = None,
) -> None:
    """Edit curation fields without changing visibility."""
    _validate_blurb(blurb)

    async def _inner() -> None:
        repo = await _repo()
        expert = await _resolve(repo, slug)
        updated = await repo.update_catalog(
            expert.id,
            catalog_rank=rank,
            blurb=blurb,
            category=category,
            tags=list(tag) if tag else None,
            clear=frozenset(clear or []),
        )
        assert updated is not None
        print_success(f"Updated {updated.name}")
        console.print(json.dumps(_curation_of(updated), indent=2))

    _run(_inner())


@app.command("feature")
def feature(
    slug: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
    off: Annotated[bool, typer.Option("--off", help="Un-feature instead")] = False,
) -> None:
    """Pin an expert to the top of the shelf (or un-pin it)."""

    async def _inner() -> None:
        repo = await _repo()
        expert = await _resolve(repo, slug)
        updated = await repo.update_catalog(expert.id, is_featured=not off)
        assert updated is not None
        print_success(f"{updated.name} {'un-featured' if off else 'featured'}")

    _run(_inner())


@app.command("reorder")
def reorder(
    slugs: Annotated[list[str], typer.Argument(help="Slugs in the order you want them")],
) -> None:
    """Set catalog_rank to 1..N across the given experts, in one pass."""

    async def _inner() -> None:
        repo = await _repo()
        for position, slug in enumerate(slugs, start=1):
            expert = await _resolve(repo, slug)
            await repo.update_catalog(expert.id, catalog_rank=position)
            console.print(f"  [dim]{position:>3}[/dim]  {expert.name}")
        print_success(f"Reordered {len(slugs)} expert(s)")

    _run(_inner())


# ── bulk workflow ───────────────────────────────────────────────────────────


@app.command("export")
def export(
    path: Annotated[
        Path | None, typer.Argument(help="File to write; omit for stdout")
    ] = None,
    all_experts: Annotated[
        bool, typer.Option("--all", help="Include private experts (default: only shared)")
    ] = False,
) -> None:
    """Dump curation for every expert as JSON — the file you edit for bulk work."""

    async def _inner() -> None:
        repo = await _repo()
        experts = await repo.list_all()
        if not all_experts:
            experts = [e for e in experts if e.catalog.visibility is not ExpertVisibility.PRIVATE]
        payload = [_curation_of(e) for e in experts]
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if path:
            path.write_text(text + "\n")
            print_success(f"Wrote {len(payload)} expert(s) to {path}")
        else:
            console.print_json(text)

    _run(_inner())


@app.command("apply")
def apply(
    path: Annotated[Path, typer.Argument(help="JSON file produced by `catalog export`")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the diff and stop")] = False,
) -> None:
    """Apply a whole edited catalog file. Shows a diff and asks before writing.

    Only fields present in each entry are touched, so a trimmed-down file is a
    valid partial update. ``null`` is meaningful — it clears the field.
    """
    if not path.exists():
        print_error(f"No such file: {path}")
        raise typer.Exit(1)
    try:
        entries = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print_error(f"{path} is not valid JSON: {exc}")
        raise typer.Exit(1) from None
    if not isinstance(entries, list):
        print_error("Expected a JSON array of expert objects.")
        raise typer.Exit(1)

    async def _inner() -> None:
        repo = await _repo()
        planned: list[tuple[Expert, dict[str, Any], list[str]]] = []

        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("name"):
                print_error(f"Skipping entry without a name: {entry!r}")
                continue
            expert = await repo.get_by_name(str(entry["name"]))
            if expert is None:
                print_error(f"Unknown expert {entry['name']!r} — skipped")
                continue
            _validate_blurb(entry.get("blurb"))
            before = _curation_of(expert)
            changes = [
                f"{k}: {before.get(k)!r} → {entry[k]!r}"
                for k in ("visibility", "featured", "rank", "blurb", "category", "tags")
                if k in entry and entry[k] != before.get(k)
            ]
            if changes:
                planned.append((expert, entry, changes))

        if not planned:
            console.print("[dim]Nothing to change.[/dim]")
            return

        console.print(f"\n[bold]{len(planned)} expert(s) will change:[/bold]\n")
        for expert, _, changes in planned:
            console.print(f"  [bold]{expert.name}[/bold]")
            for change in changes:
                console.print(f"    [dim]{change}[/dim]")
        console.print()

        if dry_run:
            return
        if not yes and not typer.confirm("Apply these changes?"):
            raise typer.Abort()

        for expert, entry, _ in planned:
            visibility = (
                ExpertVisibility(entry["visibility"]) if entry.get("visibility") else None
            )
            # An explicit null in the file means "clear this field"; an absent
            # key means "leave it alone". update_catalog needs that distinction
            # spelled out, since None is its own "leave alone" signal.
            clear = {
                column
                for key, column in (
                    ("blurb", "blurb"),
                    ("category", "category"),
                    ("rank", "catalog_rank"),
                )
                if key in entry and entry[key] is None
            }
            await repo.update_catalog(
                expert.id,
                visibility=visibility,
                is_featured=entry.get("featured"),
                catalog_rank=entry.get("rank"),
                blurb=entry.get("blurb"),
                category=entry.get("category"),
                tags=list(entry["tags"]) if entry.get("tags") is not None else None,
                clear=frozenset(clear),
            )
        print_success(f"Applied changes to {len(planned)} expert(s)")

    _run(_inner())
