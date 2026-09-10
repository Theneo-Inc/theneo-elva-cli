from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(name="mcp", help="Manage MCP servers.", no_args_is_help=True)


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List the MCP servers in a workspace."""
    from elva_cli.core.services.mcp import list_mcps

    ctx = get_ctx(click_ctx)
    result = list_mcps(base_url=ctx.settings.base_url, workspace=ctx.settings.workspace)
    ctx.out.result(result)


@app.command("show")
def show(click_ctx: typer.Context, slug: str) -> None:
    """Show one MCP server's full detail, including its runtime URL."""
    from elva_cli.core.services.mcp import show_mcp

    ctx = get_ctx(click_ctx)
    result = show_mcp(base_url=ctx.settings.base_url, workspace=ctx.settings.workspace, slug=slug)
    ctx.out.result(result)
