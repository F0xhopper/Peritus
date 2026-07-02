"""Rich renderer for chat answers."""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from peritus.chat.agent import Answer

console = Console()


def render_answer(answer: Answer, persona_name: str | None = None) -> None:
    speaker = persona_name or "Expert"
    console.print(Rule(f"[bold cyan]{speaker}[/bold cyan]", style="cyan"))
    console.print(Markdown(answer.text))

    if answer.has_contradiction:
        console.print(
            "\n[yellow]⚠ Note: the sources contain a conflicting view on this topic.[/yellow]"
        )

    if answer.sources_used:
        sources_text = "\n".join(f"  • {s}" for s in answer.sources_used)
        console.print(
            Panel(
                sources_text,
                title="[dim]Sources cited this turn[/dim]",
                border_style="dim",
                padding=(0, 1),
            )
        )
    console.print()


def render_thinking() -> None:
    console.print("[dim]Thinking…[/dim]")
