from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="whoami", help="Show who you're signed in as.", add_completion=False)


@app.command()
def whoami(click_ctx: typer.Context) -> None:
    """Show the email (and, for a personal access token, the scoped company)
    the current credentials belong to."""
    from elva_cli.core.services.whoami import whoami as whoami_service

    ctx = get_ctx(click_ctx)
    result = whoami_service(base_url=ctx.settings.base_url)
    ctx.out.result(result)
