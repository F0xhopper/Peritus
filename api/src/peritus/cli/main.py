"""peritus — grounded AI expert builder CLI."""

import asyncio

import typer

from peritus.cli.build import build_command
from peritus.cli.chat import chat_command, _chat_async
from peritus.cli.credentials import credentials_command
from peritus.cli.experts import app as experts_app, _experts_with_concepts
from peritus.cli.display import console, suite_view
from peritus.core.config import settings
from peritus.core.logging import setup_logging

app = typer.Typer(
    name="peritus",
    help="Build grounded AI subject-matter experts from multi-source corpora.",
    invoke_without_command=True,
)


@app.callback()
def default(ctx: typer.Context) -> None:
    """When invoked with no subcommand, show expert cards and launch a chat."""
    if ctx.invoked_subcommand is not None:
        return

    import questionary

    async def _pick_and_chat() -> None:
        from peritus.infrastructure.database import init_pool
        await init_pool()

        pairs = await _experts_with_concepts()
        ready = [(e, c) for e, c in pairs if e.status.value == "ready"]

        if not pairs:
            console.print("\n[dim]No experts yet. Run [bold]peritus build <topic>[/bold] to create one.[/dim]\n")
            raise typer.Exit()

        if not ready:
            console.print("[dim]No experts are ready to chat yet.[/dim]\n")
            raise typer.Exit()

        choices = [
            questionary.Choice(title=f"{e.persona_name or e.name.title()}  ({e.topic})", value=e.name)
            for e, _ in ready
        ]
        name = await questionary.select(
            "Select an expert",
            choices=choices,
            style=questionary.Style([
                ("selected", "bold cyan"),
                ("pointer", "bold cyan"),
                ("question", "bold"),
            ]),
        ).ask_async()

        if name is None:
            raise typer.Exit()

        console.print()
        await _chat_async(name)

    asyncio.run(_pick_and_chat())

app.command("build")(build_command)
app.command("chat")(chat_command)
app.command("credentials")(credentials_command)
app.add_typer(experts_app, name="experts")


@app.command("suite")
def suite() -> None:
    """Show all experts as a gallery of cards."""
    from peritus.cli.display import suite_view
    pairs = asyncio.run(_experts_with_concepts())
    suite_view(pairs)


@app.command("rebuild")
def rebuild(
    name: str = typer.Argument(..., help="Expert name or fuzzy match"),
) -> None:
    """Delete an existing expert and rebuild it from scratch."""
    from peritus.cli.build import build_command as _build
    from peritus.experts.service import ExpertService
    from peritus.infrastructure.database import get_pool, init_pool

    async def _get_topic():
        await init_pool()
        svc = ExpertService(get_pool())
        expert = await svc.get(name)
        return expert.topic

    topic = asyncio.run(_get_topic())
    build_command(topic, depth="normal", sources=None, rebuild=True)


@app.command("config")
def config(
    action: str = typer.Argument(..., help="show | set"),
    item: str | None = typer.Argument(None, help="KEY=VALUE for set"),
) -> None:
    """Show or update configuration."""
    from peritus.core.config import settings
    from peritus.cli.display import console

    if action == "show":
        console.print("[bold]Current configuration:[/bold]")
        def _key(val: str, required: bool = True) -> str:
            if val:
                return "[green]set[/green]"
            return "[red]missing[/red]" if required else "[yellow]optional — enables more sources[/yellow]"

        console.print(f"  DATABASE_URL       {_key(settings.DATABASE_URL)}")
        console.print(f"  OPENAI_API_KEY     {_key(settings.OPENAI_API_KEY)}")
        console.print(f"  ANTHROPIC_API_KEY  {_key(settings.ANTHROPIC_API_KEY)}")
        console.print(f"  MISTRAL_API_KEY    {_key(settings.MISTRAL_API_KEY, required=False)}  [dim](PDF/OCR fetcher)[/dim]")
        console.print(f"  EXA_API_KEY        {_key(settings.EXA_API_KEY, required=False)}  [dim](YouTube + Exa fetchers)[/dim]")
        console.print(f"  EMBED_MODEL        {settings.EMBED_MODEL}")
        console.print(f"  CLAUDE_MODEL       {settings.CLAUDE_MODEL}")
        console.print(f"  FAST_MODEL         {settings.FAST_MODEL}")
    elif action == "set" and item:
        import os
        from pathlib import Path
        env_file = Path(".env")
        key, _, value = item.partition("=")
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_file.write_text("\n".join(lines) + "\n")
        console.print(f"[green]Set[/green] {key}")
    else:
        console.print("[red]Usage: peritus config show | peritus config set KEY=VALUE[/red]")


def main() -> None:
    setup_logging(settings.LOG_LEVEL)
    app()
