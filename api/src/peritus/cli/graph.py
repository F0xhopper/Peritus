"""``peritus graph`` — maintenance on an expert's concept graph.

    peritus graph assign-key-concepts thomism     # place every concept in the syllabus
    peritus graph assign-key-concepts --all       # every expert with a graph

The build assigns key concepts at the end of graph extraction; this is the
backfill for graphs extracted before it did (migration 034), and the way to
re-run it after the floor in :mod:`peritus.graph.key_concepts` moves. It embeds
at most one string per key concept, so it costs a fraction of a cent.

Talks to Postgres directly, like the rest of the Python CLI.
"""

import asyncio
from typing import Annotated

import typer

from peritus.cli.display import console, print_error
from peritus.experts.domain import Expert
from peritus.experts.repository import ExpertRepository
from peritus.graph.key_concepts import assign_key_concepts
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.database import get_pool, init_pool
from peritus.infrastructure.embeddings import embed_in_batches

app = typer.Typer(help="Maintain experts' concept graphs.")


@app.command("assign-key-concepts")
def assign_key_concepts_command(
    slug: Annotated[str | None, typer.Argument(help="The expert's slug.")] = None,
    all_experts: Annotated[
        bool, typer.Option("--all", help="Every expert whose graph is built.")
    ] = False,
) -> None:
    """Assign each concept node to its nearest key concept, and store it."""
    if (slug is None) == (not all_experts):
        print_error("Name one expert, or pass --all.")
        raise typer.Exit(1)
    asyncio.run(_assign(slug, all_experts))


async def _assign(slug: str | None, all_experts: bool) -> None:
    await init_pool()
    pool = get_pool()
    experts_repo = ExpertRepository(pool)
    graph_repo = GraphRepository(pool)

    targets: list[Expert]
    if all_experts:
        targets = [e for e in await experts_repo.list_all() if e.graph_expanded]
    else:
        expert = await experts_repo.get_by_name(slug or "")
        if expert is None:
            print_error(f"No expert named {slug!r}.")
            raise typer.Exit(1)
        targets = [expert]

    for expert in targets:
        if not expert.graph_expanded:
            console.print(f"[yellow]{expert.name}[/yellow]: the graph is not built yet — skipped.")
            continue
        stats = await assign_key_concepts(
            graph_repo, expert.id, list(expert.key_concepts), embed_in_batches
        )
        console.print(
            f"[green]{expert.name}[/green]: {stats.assigned} of {stats.nodes} concepts "
            f"placed in {len(expert.key_concepts)} key concepts, {stats.unassigned} unassigned."
        )
