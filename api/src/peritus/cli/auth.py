"""peritus login / logout / whoami — email-OTP auth via the API server.

The CLI never talks to Supabase directly; it uses the API's backend-for-frontend
``/auth`` endpoints, which hold the anon key server-side.
"""

from typing import Annotated

import httpx
import typer

from peritus.cli.display import console
from peritus.cli.session import Session, clear, load, save
from peritus.core.config import settings


def _server_url() -> str:
    return settings.PERITUS_SERVER_URL.rstrip("/")


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            return body["detail"]
    except ValueError:
        pass
    return f"HTTP {resp.status_code}"


def login_command(
    email: Annotated[str | None, typer.Option("--email", help="Email to sign in with")] = None,
) -> None:
    """Sign in with an email one-time code."""
    base = _server_url()
    if not email:
        email = typer.prompt("Email").strip()

    with httpx.Client(timeout=20.0) as client:
        try:
            resp = client.post(f"{base}/auth/otp", json={"email": email})
        except httpx.HTTPError as exc:
            console.print(f"[red]Cannot reach server at {base}: {exc}[/red]")
            raise typer.Exit(1) from exc
        if resp.status_code == 503:
            console.print(
                "[yellow]This server has login disabled (dev mode) — no sign-in needed.[/yellow]"
            )
            raise typer.Exit(0)
        if resp.status_code >= 400:
            console.print(f"[red]Could not send code: {_detail(resp)}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Code sent to {email}.[/green] Check your inbox.")
        code = typer.prompt("Enter the 6-digit code").strip()

        try:
            resp = client.post(f"{base}/auth/verify", json={"email": email, "token": code})
        except httpx.HTTPError as exc:
            console.print(f"[red]Verification failed: {exc}[/red]")
            raise typer.Exit(1) from exc
        if resp.status_code >= 400:
            console.print(f"[red]Invalid code: {_detail(resp)}[/red]")
            raise typer.Exit(1)

    data = resp.json()
    user = data.get("user", {}) or {}
    save(Session(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=int(data.get("expires_at") or 0),
        user_id=user.get("id", ""),
        email=user.get("email") or email,
    ))
    console.print(f"[bold green]Signed in as {user.get('email') or email}.[/bold green]")


def logout_command() -> None:
    """Sign out and delete the cached session."""
    clear()
    console.print("[dim]Signed out.[/dim]")


def whoami_command() -> None:
    """Show the currently signed-in user."""
    session = load()
    if not session:
        console.print("[dim]Not signed in. Run [bold]peritus login[/bold].[/dim]")
        raise typer.Exit(1)
    label = session.email or "(unknown email)"
    console.print(f"[bold]{label}[/bold]  [dim]{session.user_id}[/dim]")
