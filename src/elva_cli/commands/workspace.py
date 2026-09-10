from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="workspace", help="Manage workspaces.", no_args_is_help=True)


@app.callback()
def main() -> None:
    pass


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    from elva_cli.core.services.workspace_list import list_workspaces

    ctx = get_ctx(click_ctx)
    result = list_workspaces(
        base_url=ctx.settings.base_url,
        active_workspace=ctx.settings.workspace,
        active_origin=ctx.resolution.origins.get("workspace", "default"),
    )
    ctx.out.result(result)


@app.command("switch")
def switch(
    click_ctx: typer.Context,
    name: str | None = typer.Argument(None, help="Workspace name or slug."),
    use_global: bool = typer.Option(
        False, "--global", help="Write to the user config instead of the project file."
    ),
) -> None:
    """Set the active workspace after checking membership."""
    from elva_cli.core.services.workspace_switch import (
        fetch_workspace_names,
        switch_workspace,
    )
    from elva_cli.ui import prompts

    ctx = get_ctx(click_ctx)
    requested = name
    if requested is None:
        if not ctx.interactive:
            from elva_cli.errors import UsageError

            raise UsageError(
                "workspace name is required when there is no terminal to prompt on",
                hint="Pass the workspace name, or run this in an interactive shell.",
            )
        choices = fetch_workspace_names(base_url=ctx.settings.base_url)
        if not choices:
            from elva_cli.errors import UsageError

            raise UsageError(
                "your account has no workspaces",
                hint="Create one at https://app.getelva.ai, then try again.",
            )
        requested = prompts.select(
            None,
            prompt="Which workspace?",
            choices=choices,
            flag="name",
            ctx=ctx,
        )

    result = switch_workspace(
        base_url=ctx.settings.base_url,
        cwd=ctx.cwd,
        requested=requested,
        use_global=use_global,
    )
    ctx.out.result(result)
