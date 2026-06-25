"""peritus chat — interactive REPL with credential card on entry."""

import asyncio
from typing import Annotated

import typer
from rich.console import Console

from peritus.chat.agent import ChatAgent
from peritus.chat.history import ConversationHistory
from peritus.chat.renderer import render_answer, render_thinking
from peritus.cli.display import credential_card, print_error
from peritus.core.exceptions import NotFoundError
from peritus.experts.domain import ExpertStatus
from peritus.experts.service import ExpertService
from peritus.graph.repository import GraphRepository
from peritus.infrastructure.database import get_pool, init_pool

console = Console()


def chat_command(
    name: Annotated[str, typer.Argument(help="Expert name or fuzzy match")],
) -> None:
    """Open an interactive chat session with an expert."""
    asyncio.run(_chat_async(name))


async def _chat_async(name: str) -> None:
    await init_pool()
    pool = get_pool()
    svc = ExpertService(pool)

    try:
        expert = await svc.get(name)
    except NotFoundError:
        print_error(f"No expert found matching {name!r}")
        raise typer.Exit(1)

    if expert.status != ExpertStatus.READY:
        print_error(
            f"Expert {expert.name!r} is not ready (status: {expert.status.value}). "
            "Run peritus build to complete it."
        )
        raise typer.Exit(1)

    # Show credential card on entry
    async with pool.acquire() as conn:
        source_rows = await conn.fetch(
            "SELECT * FROM sources WHERE expert_id = $1 ORDER BY quality_score DESC NULLS LAST",
            expert.id,
        )
    passed = [dict(r) for r in source_rows if r["passed"]]
    dropped = [dict(r) for r in source_rows if not r["passed"]]
    graph_repo = GraphRepository(pool)
    top_nodes = await graph_repo.get_top_nodes(expert.id, 7)

    console.print(credential_card(expert, passed, dropped, top_nodes))
    console.print()

    persona = expert.persona_name or expert.name
    console.print(f"[bold cyan]Chatting with {persona}[/bold cyan]  [dim](type 'quit' to exit)[/dim]\n")

    agent = ChatAgent(pool)
    history = ConversationHistory()

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            console.print("[dim]Session ended.[/dim]")
            break

        history.add_user(question)
        render_thinking()

        try:
            answer = await agent.respond(expert, question, history.to_messages()[:-1])
            render_answer(answer, persona_name=expert.persona_name)
            history.add_assistant(answer.text)
        except Exception as exc:
            print_error(f"Error generating response: {exc}")
