from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="config", help="Inspect resolved configuration.", no_args_is_help=True)


def _row(label: str, value: str, note: str = "") -> str:
    return f"{label:<16}{value}{'  ' + note if note else ''}"


@app.command("path")
def path(click_ctx: typer.Context) -> None:
    """Show every file the CLI reads configuration from."""
    from elva_cli.settings import paths

    ctx = get_ctx(click_ctx)
    typer.echo(_row("config dir", str(paths.config_dir())))
    typer.echo(_row("cache dir", str(paths.cache_dir())))
    for file in ctx.resolution.files:
        typer.echo(
            _row(f"{file.kind} config", str(file.path), "(found)" if file.exists else "(absent)")
        )


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """Show each setting, its value, and which layer set it."""
    ctx = get_ctx(click_ctx)
    resolution = ctx.resolution
    settings = resolution.settings
    for field in sorted(type(settings).model_fields):
        value = getattr(settings, field)
        shown = "-" if value is None else str(value)
        typer.echo(f"{field:<14}{shown:<32}{resolution.origins[field]}")
    if resolution.profiles:
        typer.echo("")
        typer.echo(f"profiles      {', '.join(resolution.profiles)}")
