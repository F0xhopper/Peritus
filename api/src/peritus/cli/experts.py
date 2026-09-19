import asyncio

import typer

from peritus.cli.display import console, experts_table, print_error, print_success, suite_view
from peritus.core.exceptions import NotFoundError
from peritus.experts.service import ExpertService
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.database import get_pool, init_pool

app = typer.Typer(help="Manage experts.")


def _run(coro):
    return asyncio.run(coro)


async def _service() -> ExpertService:
    await init_pool()
    return ExpertService(get_pool())


async def _experts_with_concepts() -> list[tuple]:
    await init_pool()
    pool = get_pool()
    svc = ExpertService(pool)
    graph = GraphRepository(pool)
    experts = await svc.list_all()
    result = []
    for expert in experts:
        concepts = await graph.get_top_nodes(expert.id, 5) if expert.status.value == "ready" else []
        result.append((expert, concepts))
    return result


@app.command("list")
def list_experts(
    table: bool = typer.Option(False, "--table", help="Show compact table instead of suite view"),
) -> None:
    """List all experts as a suite of cards."""

    async def _inner():
        pairs = await _experts_with_concepts()
        if not pairs:
            console.print(
                "[dim]No experts found. Run [bold]peritus build <topic>[/bold] to create one.[/dim]"
            )
            return
        if table:
            console.print(experts_table([e for e, _ in pairs]))
        else:
            suite_view(pairs)

    _run(_inner())


@app.command("show")
def show_expert(name: str = typer.Argument(..., help="Expert name or fuzzy match")) -> None:
    """Show details of a specific expert."""

    async def _inner():
        svc = await _service()
        try:
            expert = await svc.get(name)
        except NotFoundError:
            print_error(f"No expert found matching {name!r}")
            raise typer.Exit(1) from None
        console.print(f"\n[bold]{expert.name}[/bold]  [dim]{expert.status.value}[/dim]")
        if expert.persona_name:
            console.print(f"Persona: [cyan]{expert.persona_name}[/cyan]")
        if expert.persona_bio:
            console.print(f"\n{expert.persona_bio}")
        console.print(
            f"\nSources: {expert.source_count}  Chunks: {expert.chunk_count}  "
            f"Nodes: {expert.node_count}  Edges: {expert.edge_count}"
        )
        if expert.error:
            print_error(expert.error)

    _run(_inner())


@app.command("refresh-persona")
def refresh_persona(name: str = typer.Argument(..., help="Expert name or fuzzy match")) -> None:
    """Regenerate an expert's persona from its existing corpus.

    For experts built before a change to the persona prompt: the corpus is
    already right, only the voice is stale. One model call, no rebuild.
    """

    async def _inner():
        svc = await _service()
        try:
            expert = await svc.get(name)
        except NotFoundError:
            print_error(f"No expert found matching {name!r}")
            raise typer.Exit(1) from None

        console.print(
            f"Regenerating persona for [bold]{expert.name}[/bold] "
            f"[dim](currently {expert.persona_name or 'unnamed'})[/dim]…"
        )
        try:
            updated = await svc.regenerate_persona(expert.id)
        except NotFoundError:
            print_error(
                f"{expert.name!r} has no validated sources — build it before "
                "regenerating its persona."
            )
            raise typer.Exit(1) from None

        print_success(f"Persona regenerated: {updated.persona_name}")
        if updated.persona_bio:
            console.print(f"\n{updated.persona_bio}")

    _run(_inner())


# A local command has no build waiting on it, so it lets a throttled Wikimedia
# finish rather than reporting a timeout the operator would only retry by hand.
_CLI_PICTURE_DEADLINE = 90.0


@app.command("refresh-picture")
def refresh_picture(name: str = typer.Argument(..., help="Expert name or fuzzy match")) -> None:
    """Find this expert's picture again on Wikimedia.

    A build finds a picture once and then leaves it alone, so this is the way to
    get one for an expert built before pictures existed, or a different one when
    the first pick was wrong. Five or six HTTP requests — plus one small model
    call, only when nothing about the topic itself has a free picture.
    """

    async def _inner():
        from peritus.experts.picture import PictureSkipped

        svc = await _service()
        try:
            expert = await svc.get(name)
        except NotFoundError:
            print_error(f"No expert found matching {name!r}")
            raise typer.Exit(1) from None

        console.print(f"Searching Wikimedia for a picture of [bold]{expert.topic}[/bold]…")
        try:
            updated = await svc.refresh_picture(expert.id, deadline=_CLI_PICTURE_DEADLINE)
        except PictureSkipped as skip:
            print_error(f"No picture found for {expert.name!r} ({skip.reason}).")
            raise typer.Exit(1) from None

        picture = updated.picture
        assert picture is not None  # refresh_picture raises rather than returning empty
        print_success(f"Picture found: {picture.page_title}")
        console.print(
            f"[dim]{picture.artist or 'Unknown artist'} · {picture.license} · "
            f"{picture.file_page_url}[/dim]"
        )

    _run(_inner())


@app.command("backfill-pictures")
def backfill_pictures(
    limit: int = typer.Option(50, "--limit", help="Maximum experts to process"),
    sleep: float = typer.Option(1.0, "--sleep", help="Seconds to pause between experts"),
) -> None:
    """Give every picture-less expert a picture, paced.

    Run once by hand after deploying, never automatically: a deploy that fired
    hundreds of unattended requests at Wikimedia would be exactly the behaviour
    their API policy asks tools not to have. The pause between experts is the
    whole point of the command — raise ``--sleep`` rather than lowering it.
    """

    async def _inner():
        from peritus.experts.picture import PictureSkipped
        from peritus.experts.picture_repository import ExpertPictureRepository

        svc = await _service()
        pictures = ExpertPictureRepository(get_pool())
        missing = await pictures.list_missing(limit)
        if not missing:
            console.print("[dim]Every expert already has a picture.[/dim]")
            return

        console.print(f"Finding pictures for {len(missing)} expert(s)…\n")
        found = skipped = 0
        for i, (expert_id, slug, topic) in enumerate(missing):
            if i:
                await asyncio.sleep(sleep)
            try:
                updated = await svc.refresh_picture(expert_id, deadline=_CLI_PICTURE_DEADLINE)
            except PictureSkipped as skip:
                skipped += 1
                console.print(f"  [yellow]—[/yellow] {slug} [dim]({skip.reason})[/dim]")
                continue
            except Exception as exc:  # one bad expert must not end the run
                skipped += 1
                console.print(f"  [red]✗[/red] {slug} [dim]({type(exc).__name__}: {exc})[/dim]")
                continue
            found += 1
            picture = updated.picture
            title = picture.page_title if picture else topic
            license_name = picture.license if picture else "?"
            console.print(f"  [green]✓[/green] {slug} → {title} [dim]({license_name})[/dim]")

        console.print(f"\n{found} found, {skipped} skipped.")

    _run(_inner())


@app.command("delete")
def delete_expert(
    name: str = typer.Argument(..., help="Expert name or fuzzy match"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an expert and all its data."""

    async def _inner():
        svc = await _service()
        try:
            expert = await svc.get(name)
        except NotFoundError:
            print_error(f"No expert found matching {name!r}")
            raise typer.Exit(1) from None

        if not yes:
            confirm = typer.confirm(f"Delete expert {expert.name!r} and all its data?")
            if not confirm:
                raise typer.Abort()

        await svc.delete(expert.id)
        print_success(f"Deleted expert: {expert.name!r}")

    _run(_inner())
