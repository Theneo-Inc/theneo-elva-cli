from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from elva_cli.context import Ctx
    from elva_cli.core.services.mcp_logs_result import LogEntry

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


@app.command("logs")
def logs(
    click_ctx: typer.Context,
    slug: str,
    limit: int = typer.Option(20, "--limit", min=1, max=1000, help="How many entries to show."),
    page: int = typer.Option(1, "--page", min=1, help="Which page of --limit-sized results."),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Poll for new entries and stream them."
    ),
) -> None:
    """Show an MCP server's recent request history."""
    from elva_cli.core.services.mcp_logs import fetch_logs_window, follow_logs
    from elva_cli.ui.renderables.mcp_logs import format_log_line

    ctx = get_ctx(click_ctx)
    if follow and page != 1:
        msg = "--follow always starts from the latest entries; it can't be combined with --page."
        raise UsageError(msg)

    base_url = ctx.settings.base_url
    workspace = ctx.settings.workspace

    if not follow:
        result = fetch_logs_window(
            base_url=base_url, workspace=workspace, slug=slug, page=page, limit=limit
        )
        ctx.out.result(result)
        return

    stream = follow_logs(
        base_url=base_url,
        workspace=workspace,
        slug=slug,
        limit=limit,
        notify=ctx.out.warn,
    )
    _emit_batch(ctx, next(stream), format_log_line)
    while not _stdin_closed():
        _emit_batch(ctx, next(stream), format_log_line)


def _emit_batch(
    ctx: Ctx, entries: Iterable[LogEntry], format_line: Callable[[LogEntry], str]
) -> None:
    for entry in entries:
        if ctx.out.json_mode:
            ctx.out.stream_json(asdict(entry))
        else:
            ctx.out.stream_line(format_line(entry))


def _stdin_closed() -> bool:
    """True once stdin hits EOF -- lets `--follow` terminate instead of
    polling forever when run unattended, while an idle interactive TTY just
    keeps waiting for the next poll.
    """
    import os
    import select
    import sys

    try:
        fd = sys.stdin.fileno()
        ready, _, _ = select.select([fd], [], [], 0)
    except (OSError, ValueError):
        return False
    if not ready:
        return False
    try:
        return os.read(fd, 4096) == b""
    except OSError:
        return False
