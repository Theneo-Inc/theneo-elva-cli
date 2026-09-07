from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="auth", help="Sign in and manage credentials.", no_args_is_help=True)


@app.callback()
def _auth() -> None:
    """Forces this to stay a command group even with one subcommand today —
    Typer collapses a single-command Typer app into a flat command otherwise,
    which would make `elva auth login` fail as an unexpected extra argument."""


@app.command("login")
def login(click_ctx: typer.Context) -> None:
    """Sign in via your browser."""
    from elva_cli.core.services.auth import login as login_service

    ctx = get_ctx(click_ctx)
    result = login_service(
        base_url=ctx.settings.base_url,
        on_progress=ctx.out.hint,
        interactive=ctx.interactive,
    )
    ctx.out.result(result)
