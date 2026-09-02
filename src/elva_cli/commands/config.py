from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="config", help="Inspect resolved configuration.", no_args_is_help=True)


@app.command("path")
def path(click_ctx: typer.Context) -> None:
    """Show every file the CLI reads configuration from."""
    from elva_cli.core.services.config import describe_paths

    ctx = get_ctx(click_ctx)
    ctx.out.result(describe_paths(ctx.resolution))


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """Show each setting, its value, and which layer set it."""
    from elva_cli.core.services.config import describe_values

    ctx = get_ctx(click_ctx)
    ctx.out.result(describe_values(ctx.resolution))
