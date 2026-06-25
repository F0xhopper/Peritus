"""peritus build — orchestrates the 5-stage pipeline with live rich output."""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from peritus.core.exceptions import BuildError, ConflictError
from peritus.experts.builder import ExpertBuilder
from peritus.experts.domain import ExpertStatus
from peritus.experts.service import ExpertService
from peritus.infrastructure.database import get_pool, init_pool

console = Console()

_STAGE_LABELS = {
    "discover": "[1/5] Discovering sources",
    "validate": "[2/5] Validating with Claude",
    "chunk":    "[3/5] Chunking & embedding",
    "graph":    "[4/5] Building concept graph",
    "persona":  "[5/5] Generating persona",
}


def build_command(
    topic: Annotated[str, typer.Argument(help="Topic to build an expert on")],
    depth: Annotated[str, typer.Option("--depth", help="normal or deep")] = "normal",
    sources: Annotated[str | None, typer.Option("--sources", help="Comma-separated fetcher names")] = None,
    rebuild: bool = typer.Option(False, "--rebuild", help="Delete existing expert and rebuild"),
) -> None:
    """Build a grounded expert from multi-source corpus."""
    asyncio.run(_build_async(topic, depth, sources, rebuild))


async def _build_async(topic: str, depth: str, sources_flag: str | None, rebuild: bool) -> None:
    await init_pool()
    pool = get_pool()
    svc = ExpertService(pool)

    source_filter = [s.strip() for s in sources_flag.split(",")] if sources_flag else None

    console.print(f'\n[bold]◆ Building expert:[/bold] [cyan]"{topic}"[/cyan]\n')

    # Handle rebuild
    if rebuild:
        try:
            existing = await svc.get(topic)
            await svc.delete(existing.id)
            console.print(f"  [dim]Deleted existing expert: {existing.name!r}[/dim]")
        except Exception:
            pass

    try:
        expert = await svc.create(topic)
    except ConflictError:
        console.print(
            f"[yellow]Expert {topic!r} already exists. "
            "Use --rebuild to replace it or peritus chat to use it.[/yellow]"
        )
        raise typer.Exit(1)

    # Build progress state
    stage_state: dict[str, dict] = {
        s: {"done": 0, "total": 1, "status": "pending"}
        for s in _STAGE_LABELS
    }

    item_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    )
    item_task = item_progress.add_task("", total=1)

    async def on_stage(stage: str, state: str, done: int, total: int) -> None:
        stage_state[stage]["done"] = done
        stage_state[stage]["total"] = max(total, 1)
        stage_state[stage]["status"] = state
        if state == "starting":
            item_progress.update(item_task, description=_STAGE_LABELS[stage], total=max(total, 1), completed=0)
        elif state == "done":
            item_progress.update(item_task, completed=total)

    def on_item(count: int) -> None:
        item_progress.advance(item_task)

    builder = ExpertBuilder(pool, depth=depth, source_filter=source_filter)

    try:
        with item_progress:
            result = await builder.build(expert, on_stage=on_stage, on_item=on_item)
    except BuildError as exc:
        await svc.mark_failed(expert.id, str(exc))
        console.print(f"\n[bold red]Build failed:[/bold red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        await svc.mark_failed(expert.id, str(exc))
        console.print(f"\n[bold red]Unexpected error:[/bold red] {exc}")
        raise typer.Exit(1)

    await svc.mark_ready(expert.id)

    # Final summary panel
    persona = result.persona_name or topic.title()
    avg_q = f"{result.avg_quality:.1f}" if result.avg_quality else "—"
    console.print()
    console.rule(style="bright_blue")
    console.print(
        Panel(
            f"[bold green]Expert ready:[/bold green] [bold cyan]\"{persona}\"[/bold cyan]\n"
            f"Trained on [green]{result.source_count}[/green] sources"
            + (f"  ([dim]{result.dropped_count} dropped[/dim])" if result.dropped_count else "")
            + f" · [green]{result.chunk_count}[/green] chunks"
            + f" · [green]{result.node_count}[/green] concepts"
            + f"\nAvg quality [yellow]{avg_q}[/yellow] / 10\n"
            f"\nRun: [bold]peritus chat \"{topic}\"[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )
