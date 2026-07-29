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
            console.print("[dim]No experts found. Run [bold]peritus build <topic>[/bold] to create one.[/dim]")
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
