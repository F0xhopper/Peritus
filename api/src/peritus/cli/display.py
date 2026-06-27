"""Rich terminal primitives shared across all CLI commands."""

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


def print_error(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")


def print_success(msg: str) -> None:
    console.print(f"[bold green]✓[/bold green] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def expert_status_badge(status: str) -> Text:
    colours = {"ready": "green", "building": "yellow", "failed": "red"}
    icons = {"ready": "●", "building": "◌", "failed": "✗"}
    colour = colours.get(status, "white")
    icon = icons.get(status, "·")
    return Text(f"{icon} {status}", style=f"bold {colour}")


def _expert_card(expert, top_concepts: list[dict], width: int = 40) -> Panel:
    """Single expert card for the suite view."""
    status_colours = {"ready": "bright_blue", "building": "yellow", "failed": "red"}
    border = status_colours.get(expert.status.value, "dim")

    status_icon = {
        "ready": "[bold green]●[/bold green]",
        "building": "[bold yellow]◌[/bold yellow]",
        "failed": "[bold red]✗[/bold red]",
    }
    persona = expert.persona_name or expert.name.title()
    inner = width - 6  # account for panel border + padding

    lines: list[str] = []
    lines.append(f"[bold white]{persona}[/bold white]")
    lines.append(f"[dim]{expert.topic.title()}[/dim]")
    lines.append("")
    lines.append(status_icon.get(expert.status.value, "·") + f"  [dim]{expert.status.value}[/dim]")

    if expert.persona_bio:
        bio = expert.persona_bio[: inner * 3].rstrip()
        if len(expert.persona_bio) > inner * 3:
            bio += "…"
        lines.append("")
        lines.append(f"[dim]{bio}[/dim]")

    avg_q = f"{expert.avg_quality:.1f}" if expert.avg_quality is not None else "—"
    built = expert.created_at.strftime("%Y-%m-%d") if expert.created_at else "—"
    lines.append("")
    lines.append(f"[cyan]{expert.source_count}[/cyan] sources  [cyan]{expert.chunk_count}[/cyan] chunks")
    lines.append(f"[cyan]{expert.node_count}[/cyan] concepts  [cyan]{expert.edge_count}[/cyan] edges")
    lines.append(f"Quality [yellow]{avg_q}[/yellow]/10  Built [dim]{built}[/dim]")

    if top_concepts:
        labels = "  ".join(c["label"] for c in top_concepts[:5])
        if len(labels) > inner:
            labels = labels[:inner - 1] + "…"
        lines.append("")
        lines.append(f"[dim]{labels}[/dim]")

    if expert.status.value == "ready":
        lines.append("")
        lines.append(f'[dim]peritus chat "{expert.name}"[/dim]')
    elif expert.error:
        lines.append("")
        lines.append(f"[red dim]{expert.error[:inner]}[/red dim]")

    return Panel(
        "\n".join(lines),
        border_style=border,
        padding=(1, 2),
        width=width,
    )


def suite_view(experts_with_concepts: list[tuple]) -> None:
    """Render all experts as a responsive gallery of cards."""
    if not experts_with_concepts:
        console.print(
            "\n[dim]No experts yet. Run [bold]peritus build <topic>[/bold] to create one.[/dim]\n"
        )
        return

    terminal_width = console.width
    # card width: aim for ~42 cols but shrink to fit; minimum 30
    card_min, card_ideal = 30, 42
    gap = 2  # Columns adds a small gap between cards
    cols_per_row = max(1, (terminal_width + gap) // (card_ideal + gap))
    card_width = max(card_min, (terminal_width - gap * (cols_per_row - 1)) // cols_per_row)

    console.print()
    console.rule("[bold]Your Expert Suite[/bold]", style="bright_blue")
    console.print()

    cards = [_expert_card(e, c, width=card_width) for e, c in experts_with_concepts]

    for i in range(0, len(cards), cols_per_row):
        console.print(Columns(cards[i : i + cols_per_row], equal=True, expand=False))
        if i + cols_per_row < len(cards):
            console.print()

    console.print()
    ready = sum(1 for e, _ in experts_with_concepts if e.status.value == "ready")
    total = len(experts_with_concepts)
    console.print(f"  [dim]{ready}/{total} ready  ·  peritus build <topic> to add more[/dim]\n")


def experts_table(experts: list) -> Table:
    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("Name", style="bold cyan")
    t.add_column("Status")
    t.add_column("Sources", justify="right")
    t.add_column("Chunks", justify="right")
    t.add_column("Avg Q", justify="right")
    t.add_column("Built")
    for e in experts:
        avg_q = f"{e.avg_quality:.1f}" if e.avg_quality is not None else "—"
        built = e.created_at.strftime("%Y-%m-%d") if e.created_at else "—"
        t.add_row(
            e.name,
            expert_status_badge(e.status.value),
            str(e.source_count),
            str(e.chunk_count),
            avg_q,
            built,
        )
    return t


def credential_card(expert, passed_sources: list, dropped_sources: list, top_concepts: list) -> Panel:
    from rich.columns import Columns

    lines: list[str] = []

    # Header
    persona = expert.persona_name or expert.name
    lines.append(f"[bold white]{persona}[/bold white]")
    lines.append(f"[dim]Specialist in {expert.topic.title()}[/dim]")
    lines.append("")

    avg_q = f"{expert.avg_quality:.1f} / 10" if expert.avg_quality is not None else "—"
    lines.append(f"Built        [cyan]{expert.created_at.strftime('%Y-%m-%d')}[/cyan]")
    lines.append(f"Sources      [green]{expert.source_count} validated[/green]")
    lines.append(
        f"Corpus       [cyan]{expert.chunk_count} chunks · "
        f"{expert.node_count} concepts · {expert.edge_count} edges[/cyan]"
    )
    lines.append(f"Avg quality  [yellow]{avg_q}[/yellow]")

    if passed_sources:
        lines.append("")
        lines.append("[bold]SOURCES[/bold]")
        by_type: dict[str, list] = {}
        for s in passed_sources:
            by_type.setdefault(s["source_type"], []).append(s)
        for stype, srcs in by_type.items():
            lines.append(f"  [bold cyan]{stype.title()} ({len(srcs)})[/bold cyan]")
            for i, s in enumerate(srcs):
                prefix = "└─" if i == len(srcs) - 1 else "├─"
                title = s["title"][:45].ljust(45)
                q = f"Q:{s['quality_score']:.1f}" if s["quality_score"] else ""
                r = f"R:{s['relevance_score']:.1f}" if s["relevance_score"] else ""
                lines.append(f"  {prefix} {title}  [dim]{q}  {r}[/dim]")

    if top_concepts:
        lines.append("")
        lines.append("[bold]TOP CONCEPTS[/bold]")
        lines.append("  " + " · ".join(c["label"] for c in top_concepts[:10]))

    return Panel(
        "\n".join(lines),
        title="[bold]EXPERT CREDENTIALS[/bold]",
        border_style="bright_blue",
        padding=(1, 2),
    )
