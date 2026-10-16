from __future__ import annotations

from pathlib import Path  # noqa: TC003

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="apply", help="Apply a reviewed Elva plan.", add_completion=False)


@app.command()
def apply(click_ctx: typer.Context, file: Path) -> None:
    """Apply or resume a reviewed plan. Requires --yes in CI. Never publishes."""
    from elva_cli.commands.contract import _confirm
    from elva_cli.core.services.plan import apply_plan, read_plan

    ctx = get_ctx(click_ctx)
    ctx.out.result(
        apply_plan(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            plan=read_plan(file),
            confirm=_confirm(ctx),
        )
    )
