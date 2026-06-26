"""peritus build — orchestrates the 5-stage pipeline with live rich output."""

import asyncio
import math
from collections import OrderedDict
from typing import Annotated

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from peritus.core.exceptions import BuildError, ConflictError
from peritus.experts.builder import ExpertBuilder
from peritus.experts.service import ExpertService
from peritus.infrastructure.database import get_pool, init_pool

console = Console()

_FETCHER_LABELS = {
    "wikipedia": "Wikipedia",
    "gutenberg": "Gutenberg",
    "arxiv":     "ArXiv",
    "pdf":       "PDF/Scholar",
    "youtube":   "YouTube",
    "exa":       "Exa",
    "web":       "Web",
}

_BAR_WIDTH = 28


def _bar(done: int, total: int) -> str:
    if total == 0:
        return "░" * _BAR_WIDTH
    filled = min(_BAR_WIDTH, int(_BAR_WIDTH * done / total))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


class BuildDisplay:
    """Stateful display object — Rich calls __rich__() on each Live refresh."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.stage = 0

        # Stage 1
        self.all_fetchers: list[str] = []
        self.fetcher_results: OrderedDict[str, dict] = OrderedDict()

        # Stage 2
        self.validated: list[dict] = []
        self.validate_total = 0

        # Stage 3
        self.ingested = 0
        self.ingested_total = 0
        self.total_chunks = 0

        # Stage 4
        self.concepts: list[str] = []
        self.graph_batches_done = 0
        self.graph_batches_total = 0
        self.node_count = 0
        self.edge_count = 0

        # Stage 5
        self.persona_name: str | None = None

    def __rich__(self) -> Group:
        lines: list[Text] = []
        lines.append(Text.from_markup(
            f'\n[bold]◆ Building expert:[/bold] [cyan]"{self.topic}"[/cyan]\n'
        ))

        if self.stage >= 1:
            lines.append(Text.from_markup("  [bold][1/5] Discovering sources[/bold]"))
            for name in self.all_fetchers:
                label = _FETCHER_LABELS.get(name, name)
                info = self.fetcher_results.get(name)
                if info is None:
                    lines.append(Text.from_markup(f"    [dim]{label:<12}  …[/dim]"))
                elif info.get("skipped"):
                    lines.append(Text.from_markup(
                        f"    [dim]{label:<12}  ⊘  skipped ({info.get('reason', '')})[/dim]"
                    ))
                else:
                    count = info["count"]
                    noun = "found" if count else "none"
                    colour = "green" if count else "dim"
                    lines.append(Text.from_markup(
                        f"    [dim]{label:<12}[/dim]  [{colour}]✓  {count} {noun}[/{colour}]"
                    ))

            if self.fetcher_results:
                total_found = sum(
                    v.get("count", 0) for v in self.fetcher_results.values()
                    if not v.get("skipped")
                )
                lines.append(Text.from_markup(f"    [dim]{'─' * 32}[/dim]"))
                lines.append(Text.from_markup(f"    [dim]{total_found} sources discovered[/dim]"))

        if self.stage >= 2:
            lines.append(Text.from_markup(""))
            lines.append(Text.from_markup("  [bold][2/5] Validating sources[/bold]"))
            for v in self.validated:
                title = v["title"][:52]
                scores = f"[dim]Q:{v['q']:.1f}  R:{v['r']:.1f}[/dim]"
                if v["passed"]:
                    lines.append(Text.from_markup(
                        f"    [green]✓[/green]  {title:<52}  {scores}"
                    ))
                else:
                    reason = f"  [dim]{v['drop_reason']}[/dim]" if v.get("drop_reason") else ""
                    lines.append(Text.from_markup(
                        f"    [red]✗[/red]  [dim]{title:<52}  Q:{v['q']:.1f}  R:{v['r']:.1f}{reason}[/dim]"
                    ))

            if len(self.validated) == self.validate_total and self.validate_total:
                passed = sum(1 for v in self.validated if v["passed"])
                dropped = len(self.validated) - passed
                summary = f"[green]{passed} validated[/green]"
                if dropped:
                    summary += f"  [dim]({dropped} dropped)[/dim]"
                lines.append(Text.from_markup(f"    [dim]{'─' * 32}[/dim]"))
                lines.append(Text.from_markup(f"    {summary}"))

        if self.stage >= 3:
            lines.append(Text.from_markup(""))
            lines.append(Text.from_markup("  [bold][3/5] Reading & embedding[/bold]"))
            bar = _bar(self.ingested, self.ingested_total)
            lines.append(Text.from_markup(
                f"    [cyan]{bar}[/cyan]  "
                f"[dim]{self.ingested}/{self.ingested_total} sources  ·  "
                f"{self.total_chunks} chunks[/dim]"
            ))

        if self.stage >= 4:
            lines.append(Text.from_markup(""))
            lines.append(Text.from_markup("  [bold][4/5] Extracting concept graph[/bold]"))
            if self.concepts:
                recent = "  ·  ".join(self.concepts[-7:])
                lines.append(Text.from_markup(f"    [dim]{recent}[/dim]"))
            bar = _bar(self.graph_batches_done, max(self.graph_batches_total, 1))
            lines.append(Text.from_markup(
                f"    [cyan]{bar}[/cyan]  "
                f"[dim]{self.node_count} nodes  ·  {self.edge_count} edges[/dim]"
            ))

        if self.stage >= 5:
            lines.append(Text.from_markup(""))
            lines.append(Text.from_markup("  [bold][5/5] Generating persona[/bold]"))
            if self.persona_name:
                lines.append(Text.from_markup(
                    f"    [bold cyan]→ {self.persona_name}[/bold cyan]"
                ))
            else:
                lines.append(Text.from_markup("    [dim]…[/dim]"))

        lines.append(Text(""))
        return Group(*lines)


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

    display = BuildDisplay(topic)

    async def on_event(event: dict) -> None:
        etype = event["type"]

        if etype == "discovery_started":
            display.stage = 1
            display.all_fetchers = event["fetchers"]

        elif etype == "fetcher_done":
            display.fetcher_results[event["name"]] = {
                "count": event["count"],
                "skipped": event.get("skipped", False),
                "reason": event.get("reason", ""),
            }

        elif etype == "stage":
            display.stage = event["stage"]
            if event["stage"] == 2:
                display.validate_total = event.get("total", 0)
            elif event["stage"] == 3:
                display.ingested_total = event.get("total", 0)
            elif event["stage"] == 4:
                display.graph_batches_total = event.get("total_batches", 1)

        elif etype == "source_validated":
            display.validated.append(event)

        elif etype == "source_ingested":
            display.ingested += 1
            display.total_chunks = event["total_chunks"]

        elif etype == "graph_batch_done":
            display.graph_batches_done += 1
            new_labels = [l for l in event.get("labels", []) if l not in display.concepts]
            display.concepts.extend(new_labels)
            display.node_count = sum(
                len(e.get("labels", [])) for e in [event]
            )
            display.edge_count += event.get("edges", 0)
            # Accumulate actual totals
            display.node_count = len(display.concepts)

        elif etype == "persona_ready":
            display.persona_name = event["name"]

    builder = ExpertBuilder(pool, depth=depth, source_filter=source_filter)

    try:
        with Live(display, console=console, refresh_per_second=8):
            result = await builder.build(expert, on_event=on_event)
    except BuildError as exc:
        await svc.mark_failed(expert.id, str(exc))
        console.print(f"\n[bold red]Build failed:[/bold red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        await svc.mark_failed(expert.id, str(exc))
        console.print(f"\n[bold red]Unexpected error:[/bold red] {exc}")
        import traceback; traceback.print_exc()
        raise typer.Exit(1)

    await svc.mark_ready(expert.id)

    persona = result.persona_name or topic.title()
    avg_q = f"{result.avg_quality:.1f}" if result.avg_quality else "—"
    console.print()
    console.rule(style="bright_blue")
    console.print(
        Panel(
            f"[bold green]Expert ready:[/bold green] [bold cyan]\"{persona}\"[/bold cyan]\n"
            f"Trained on [green]{result.source_count}[/green] sources"
            + f" · [green]{result.chunk_count}[/green] chunks"
            + f" · [green]{result.node_count}[/green] concepts\n"
            + f"Avg quality [yellow]{avg_q}[/yellow] / 10\n\n"
            f"Run: [bold]peritus chat \"{topic}\"[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )
