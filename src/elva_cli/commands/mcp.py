from __future__ import annotations

from dataclasses import asdict
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import ExitCode, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from elva_cli.context import Ctx
    from elva_cli.core.services.mcp_create_result import McpCreateResult, McpDryRunResult
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


@app.command("create")
def create(
    click_ctx: typer.Context,
    name: str | None = typer.Option(None, "--name", help="Name for the new MCP server."),
    operations: list[str] = typer.Option(
        [],
        "--operations",
        help=(
            'Operation to include, "METHOD /path" (repeat for more, or pass a single '
            "- to read a bulk list from stdin). Omit to include every operation."
        ),
    ),
    auth_type: str = typer.Option(
        "none",
        "--auth-type",
        help=(
            "none, bearer, or api_key. Anything else (oauth, openid_connect, "
            "basic, jwt) needs --from."
        ),
    ),
    api_key_header: str | None = typer.Option(
        None, "--api-key-header", help="Only with --auth-type api_key."
    ),
    api_key_in: str | None = typer.Option(
        None, "--api-key-in", help="header or query. Only with --auth-type api_key."
    ),
    base_url: str | None = typer.Option(None, "--base-url"),
    timeout: int | None = typer.Option(
        None, "--timeout", help="Upstream request timeout in ms (1000-300000)."
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from",
        metavar="FILE",
        help="The full request body as JSON. Not combinable with the flags above.",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        metavar="REF",
        help=(
            "env:NAME, file:PATH, or - for stdin -- never the secret itself. Only applies "
            "when --from's authConfig.type is oauth or openid_connect."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report the tool count and operations without creating anything."
    ),
) -> None:
    """Generate an MCP server from a collection."""
    from elva_cli.core.services import mcp_create as service

    ctx = get_ctx(click_ctx)
    if operations == ["-"] and client_secret == "-":
        raise UsageError(
            "--operations - and --client-secret - can't both read from stdin",
            hint="Use env:NAME or file:PATH for --client-secret instead.",
        )
    body = _build_body(
        name=name,
        operations=operations,
        auth_type=auth_type,
        api_key_header=api_key_header,
        api_key_in=api_key_in,
        base_url=base_url,
        timeout=timeout,
        from_file=from_file,
    )
    if client_secret is not None:
        from elva_cli.ui.secrets import read_secret

        body = service.merge_secret(body, read_secret(client_secret, flag="--client-secret"))

    _confirm_publish(ctx, dry_run=dry_run)

    result: McpDryRunResult | McpCreateResult
    if dry_run:
        result = service.dry_run_mcp(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            collection=ctx.settings.collection,
            body=body,
        )
    else:
        result = service.create_mcp(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            collection=ctx.settings.collection,
            body=body,
        )
    ctx.out.result(result)


def _build_body(
    *,
    name: str | None,
    operations: list[str],
    auth_type: str,
    api_key_header: str | None,
    api_key_in: str | None,
    base_url: str | None,
    timeout: int | None,
    from_file: Path | None,
) -> dict[str, Any]:
    """Which of --from or the individual flags to build the request body from."""
    from elva_cli.core.services import mcp_create as service

    flag_given = bool(
        name
        or operations
        or auth_type != "none"
        or api_key_header
        or api_key_in
        or base_url
        or timeout is not None
    )
    if from_file is not None and flag_given:
        raise UsageError("give either --from or the individual flags, not both")

    if from_file is not None:
        return service.build_body_from_file(from_file)

    if name is None:
        raise UsageError(
            "--name is required", hint="Or pass --from with a full config, including mcpName."
        )
    return service.build_body_from_flags(
        name=name,
        operations=_resolve_operations(operations),
        auth_type=auth_type,
        api_key_header=api_key_header,
        api_key_in=api_key_in,
        base_url=base_url,
        timeout=timeout,
    )


def _confirm_publish(ctx: Ctx, *, dry_run: bool) -> None:
    """Create publishes immediately."""
    if dry_run:
        return

    from elva_cli.ui import prompts

    ctx.out.warn(
        "This creates and immediately publishes a live, publicly reachable MCP "
        "server -- there is no draft state yet."
    )
    if not prompts.confirm(None, prompt="Create and publish this MCP server now?", ctx=ctx):
        ctx.out.hint("Aborted; nothing was created.")
        raise typer.Exit(ExitCode.OK)


def _resolve_operations(operations: list[str]) -> tuple[str, ...] | None:
    """Repeated --operations values, or a bulk list read from stdin when the
    only value given is the literal "-"."""
    if not operations:
        return None
    if "-" in operations and operations != ["-"]:
        raise UsageError(
            "--operations - reads a bulk list from stdin and can't be combined "
            "with other --operations values"
        )
    if operations != ["-"]:
        return tuple(operations)

    import json
    import sys

    raw = sys.stdin.read()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return tuple(parsed)
    return tuple(line.strip() for line in raw.splitlines() if line.strip())


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
