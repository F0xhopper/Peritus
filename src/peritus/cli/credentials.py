import asyncio
from typing import Annotated

import typer

from peritus.cli.display import console, credential_card, print_error
from peritus.core.exceptions import NotFoundError
from peritus.experts.service import ExpertService
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.database import get_pool, init_pool


def credentials_command(
    name: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
    show_sources: bool = typer.Option(False, "--sources", help="Show all passed sources"),
    show_dropped: bool = typer.Option(False, "--dropped", help="Show dropped sources"),
    show_graph: bool = typer.Option(False, "--graph", help="Show concept map summary"),
) -> None:
    """Show the credential card for an expert."""
    asyncio.run(_credentials_async(name, show_sources, show_dropped, show_graph))


async def _credentials_async(
    name: str,
    show_sources: bool,
    show_dropped: bool,
    show_graph: bool,
) -> None:
    await init_pool()
    pool = get_pool()
    svc = ExpertService(pool)

    try:
        expert = await svc.get(name)
    except NotFoundError:
        print_error(f"No expert found matching {name!r}")
        raise typer.Exit(1)

    # Fetch sources from DB
    async with pool.acquire() as conn:
        source_rows = await conn.fetch(
            "SELECT * FROM sources WHERE expert_id = $1 ORDER BY quality_score DESC NULLS LAST",
            expert.id,
        )

    passed = [dict(r) for r in source_rows if r["passed"]]
    dropped = [dict(r) for r in source_rows if not r["passed"]]

    # Top concepts
    graph_repo = GraphRepository(pool)
    top_nodes = await graph_repo.get_top_nodes(expert.id, 10) if show_graph or True else []

    show_passed = passed if (show_sources or not show_dropped) else []
    show_drop = dropped if show_dropped else (dropped if not show_sources else [])

    console.print(credential_card(expert, show_passed, show_drop, top_nodes))

    if show_graph and top_nodes:
        console.print("\n[bold]Concept Graph Summary[/bold]")
        for node in top_nodes[:15]:
            console.print(
                f"  [cyan]{node['label']}[/cyan]  "
                f"[dim]{node.get('node_type', '')} · {node.get('degree', 0)} connections[/dim]"
            )
