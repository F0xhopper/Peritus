"""peritus — grounded AI expert builder CLI."""

import asyncio

import typer

from peritus.cli.build import build_command
from peritus.cli.chat import chat_command
from peritus.cli.credentials import credentials_command
from peritus.cli.experts import app as experts_app, _experts_with_concepts

app = typer.Typer(
    name="peritus",
    help="Build grounded AI subject-matter experts from multi-source corpora.",
    no_args_is_help=True,
)

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
    # Resolve the name to get the topic, then rebuild
    import asyncio
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
        console.print(f"  DATABASE_URL       {'[green]set[/green]' if settings.DATABASE_URL else '[red]missing[/red]'}")
        console.print(f"  OPENAI_API_KEY     {'[green]set[/green]' if settings.OPENAI_API_KEY else '[red]missing[/red]'}")
        console.print(f"  ANTHROPIC_API_KEY  {'[green]set[/green]' if settings.ANTHROPIC_API_KEY else '[red]missing[/red]'}")
        console.print(f"  EXA_API_KEY        {'[green]set[/green]' if settings.EXA_API_KEY else '[yellow]optional[/yellow]'}")
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
    app()
