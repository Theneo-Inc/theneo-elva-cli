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


@app.command("get")
def get(click_ctx: typer.Context, key: str = typer.Argument(..., help="Setting name.")) -> None:
    """Print the resolved value of one setting, and nothing else."""
    from elva_cli.core.services.config import read_setting

    ctx = get_ctx(click_ctx)
    ctx.out.result(read_setting(ctx.resolution, key))


@app.command("set")
def set_(
    click_ctx: typer.Context,
    key: str = typer.Argument(..., help="Setting name."),
    value: str = typer.Argument(..., help="Value to store."),
    use_global: bool = typer.Option(
        False, "--global", help="Write to the user config instead of the project file."
    ),
) -> None:
    """Write a setting to the project file, or --global for the user config."""
    from elva_cli.core.services.config import write_setting

    ctx = get_ctx(click_ctx)
    ctx.out.result(write_setting(cwd=ctx.cwd, key=key, value=value, use_global=use_global))


@app.command("unset")
def unset(
    click_ctx: typer.Context,
    key: str = typer.Argument(..., help="Setting name."),
    use_global: bool = typer.Option(
        False, "--global", help="Write to the user config instead of the project file."
    ),
) -> None:
    """Remove a setting from the project file, or --global for the user config."""
    from elva_cli.core.services.config import clear_setting

    ctx = get_ctx(click_ctx)
    ctx.out.result(clear_setting(cwd=ctx.cwd, key=key, use_global=use_global))
