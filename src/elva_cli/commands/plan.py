from __future__ import annotations

from pathlib import Path  # noqa: TC003

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="plan", help="Inspect and resume AI planning jobs.", no_args_is_help=True)


@app.command("show")
def show(
    click_ctx: typer.Context,
    job_id: str,
    out: Path | None = typer.Option(None, help="Save the reviewed plan to a new JSON file."),
) -> None:
    """Wait for a planning job and retrieve its plan. Does not apply it."""
    from elva_cli.core.services.plan import planning_job, save_plan

    ctx = get_ctx(click_ctx)
    result = planning_job(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        job_id=job_id,
        progress=ctx.out.hint,
    )
    save_plan(result, out)
    ctx.out.result(result)


@app.callback()
def root() -> None:
    """Inspect planning jobs."""
