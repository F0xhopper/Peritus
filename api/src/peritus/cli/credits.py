"""``peritus credits`` — issue and inspect build credits by hand.

This is the manual grant path, and today it is the *only* way credits enter the
system: no payment provider is integrated. A founder runs

    peritus credits grant alice@lab.edu 20 --reason "pilot"

and that customer can build. When a provider is eventually chosen, its webhook
calls the same ``EntitlementService.grant`` with its own source/external_ref;
nothing here needs to change.

Talks to Postgres directly, like the rest of the Python CLI — an operator tool,
not an API client.
"""

import asyncio
from typing import Annotated

import typer

from peritus.billing.domain import PLANS, credit_cost, get_plan, spend_cap_usd
from peritus.billing.service import EntitlementService
from peritus.billing.settings import settings as billing_settings
from peritus.cli.display import console, print_error, print_success
from peritus.experts.domain import ExpertTier
from peritus.infrastructure.database import get_pool, init_pool

app = typer.Typer(help="Issue and inspect build credits.")


async def _service() -> EntitlementService:
    await init_pool()
    return EntitlementService(get_pool())


def _run(coro):
    return asyncio.run(coro)


async def _resolve(service: EntitlementService, who: str) -> str:
    owner_id = await service.resolve_owner(who)
    if not owner_id:
        print_error(
            f"No account matching {who!r}. Accounts are provisioned on first sign-in; "
            "grant by user uuid if they have never called the API."
        )
        raise typer.Exit(1)
    return owner_id


@app.command("show")
def show(
    who: Annotated[str, typer.Argument(help="Account email or owner uuid")],
) -> None:
    """Show an account's plan, balance and recent ledger entries."""

    async def _inner() -> None:
        service = await _service()
        owner_id = await _resolve(service, who)
        state = await service.credit_state(owner_id)
        console.print(
            f"\n[bold]{who}[/bold]  [dim]{owner_id}[/dim]\n"
            f"  Plan      [cyan]{state.plan.display_name}[/cyan]\n"
            f"  Balance   [bold green]{state.balance}[/bold green] credits"
            f"  [dim](granted {state.granted}, consumed {state.consumed}, "
            f"held {state.held})[/dim]"
        )
        if not billing_settings.CREDITS_ENFORCED:
            console.print("  [yellow]Credit enforcement is OFF for this deployment.[/yellow]")

        console.print("\n  [bold]Price ladder[/bold]")
        for tier in ExpertTier:
            included = "included" if tier in state.plan.allowed_tiers else "[dim]not on plan[/dim]"
            cap = spend_cap_usd(tier, state.plan, state.spend_cap_override_usd)
            console.print(
                f"    {tier.value:<9} {credit_cost(tier):>2} credits  "
                f"[dim]cap ${cap:.2f}[/dim]  {included}"
            )

        entries = await service.ledger(owner_id, limit=10)
        if entries:
            console.print("\n  [bold]Recent ledger[/bold]")
            for e in entries:
                sign = "+" if e.delta > 0 else ""
                colour = "green" if e.delta > 0 else "yellow"
                cost = f"  [dim]${e.cost_usd:.2f} spent[/dim]" if e.cost_usd else ""
                console.print(
                    f"    [{colour}]{sign}{e.delta:>4}[/{colour}]  "
                    f"[dim]{e.created_at:%Y-%m-%d}  {e.entry_type.value:<7}"
                    f"{e.reason or ''}[/dim]{cost}"
                )
        console.print()

    _run(_inner())


@app.command("grant")
def grant(
    who: Annotated[str, typer.Argument(help="Account email or owner uuid")],
    amount: Annotated[int, typer.Argument(help="Credits to add (negative claws back)")],
    reason: Annotated[str | None, typer.Option("--reason", "-r")] = None,
    plan: Annotated[
        str | None, typer.Option("--plan", help=f"Also move to a plan: {', '.join(PLANS)}")
    ] = None,
    actor: Annotated[str, typer.Option("--actor", help="Who is issuing this")] = "cli",
) -> None:
    """Issue credits to an account. The manual billing path."""
    if plan and plan not in PLANS:
        print_error(f"Unknown plan {plan!r}. Known plans: {', '.join(PLANS)}")
        raise typer.Exit(1)

    async def _inner() -> None:
        service = await _service()
        owner_id = await service.resolve_owner(who)
        if not owner_id:
            print_error(f"No account matching {who!r}")
            raise typer.Exit(1)
        if plan:
            await service.set_plan(owner_id, get_plan(plan), actor=actor)
        balance = await service.grant(
            owner_id,
            amount,
            reason=reason or "Manual grant",
            actor=actor,
            email=who if "@" in who else None,
        )
        print_success(f"{who} now has {balance} credit(s)")

    _run(_inner())


@app.command("plan")
def set_plan(
    who: Annotated[str, typer.Argument(help="Account email or owner uuid")],
    plan: Annotated[str, typer.Argument(help=f"One of: {', '.join(PLANS)}")],
    actor: Annotated[str, typer.Option("--actor")] = "cli",
) -> None:
    """Move an account onto a plan. Does not grant the plan's credits — use `grant`."""
    if plan not in PLANS:
        print_error(f"Unknown plan {plan!r}. Known plans: {', '.join(PLANS)}")
        raise typer.Exit(1)

    async def _inner() -> None:
        service = await _service()
        owner_id = await _resolve(service, who)
        await service.set_plan(owner_id, get_plan(plan), actor=actor)
        print_success(f"{who} is now on the {plan} plan")

    _run(_inner())


@app.command("accounts")
def list_accounts(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
) -> None:
    """List accounts with their plan and balance."""

    async def _inner() -> None:
        service = await _service()
        rows = await service.list_accounts(limit)
        if not rows:
            console.print("[dim]No accounts yet.[/dim]")
            return
        for row in rows:
            console.print(
                f"  [bold]{row.get('email') or row['owner_id']}[/bold]  "
                f"[cyan]{row.get('plan', 'free')}[/cyan]  "
                f"[green]{row.get('balance', 0)}[/green] credits"
            )

    _run(_inner())


@app.command("usage")
def usage(
    job_id: Annotated[int, typer.Argument(help="Build job id")],
) -> None:
    """Show what one build actually cost, broken down by stage and model."""

    async def _inner() -> None:
        service = await _service()
        data = await service.usage_for_job(job_id)
        if not data:
            print_error(f"No build job {job_id}")
            raise typer.Exit(1)
        cap = f" / cap ${data['spend_cap_usd']:.2f}" if data.get("spend_cap_usd") else ""
        console.print(
            f"\n[bold]Build job {job_id}[/bold]  [dim]{data['status']}[/dim]\n"
            f"  Total  [bold]${data['cost_usd']:.4f}[/bold]{cap}\n"
            f"  Tokens [dim]{data['input_tokens']:,} in · {data['output_tokens']:,} out · "
            f"{data['embed_tokens']:,} embed[/dim]"
        )
        if data.get("cap_exceeded_at"):
            console.print("  [red]Aborted on its spend cap.[/red]")
        if data["by_stage"]:
            console.print("\n  [bold]By stage[/bold]")
            for row in data["by_stage"]:
                console.print(
                    f"    {row['stage']:<20} ${row['cost_usd']:>8.4f}  "
                    f"[dim]{row['calls']} call(s)[/dim]"
                )
        if data["by_model"]:
            console.print("\n  [bold]By model[/bold]")
            for row in data["by_model"]:
                console.print(
                    f"    {row['model']:<32} {row['mode']:<6} ${row['cost_usd']:>8.4f}  "
                    f"[dim]{row['calls']} call(s)[/dim]"
                )
        console.print()

    _run(_inner())
