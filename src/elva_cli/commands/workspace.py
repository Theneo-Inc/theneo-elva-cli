from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="workspace", help="Manage workspaces.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keeps `workspace` a command group for future `workspace switch`."""


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List the workspaces you belong to."""
    from elva_cli.core.services.workspace_list import list_workspaces

    ctx = get_ctx(click_ctx)
    result = list_workspaces(
        base_url=ctx.settings.base_url,
        active_workspace=ctx.settings.workspace,
        active_origin=ctx.resolution.origins.get("workspace", "default"),
    )
    ctx.out.result(result)
