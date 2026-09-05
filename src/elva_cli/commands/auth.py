from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="auth", help="Sign in and manage credentials.", no_args_is_help=True)


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


@app.command("logout")
def logout(click_ctx: typer.Context) -> None:
    """Sign out and forget your stored credentials."""
    from elva_cli.auth import ENV_TOKEN
    from elva_cli.core.services.auth import logout as logout_service

    ctx = get_ctx(click_ctx)
    result = logout_service(base_url=ctx.settings.base_url)
    ctx.out.result(result)
    if ctx.env.get(ENV_TOKEN):
        ctx.out.warn(
            f"{ENV_TOKEN} is set and will still be used to authenticate. "
            "Unset it to fully sign out."
        )
