from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import ElvaError, ExitCode
from elva_cli.safe_text import printable

if TYPE_CHECKING:
    from collections.abc import Callable

    from elva_cli.context import Ctx
    from elva_cli.core.services.repo_result import RepoScanResult

app = typer.Typer(name="repo", help="Connect and sync GitHub repositories.", no_args_is_help=True)


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List your connected GitHub repositories in the selected workspace."""
    from elva_cli.core.services.repo import list_repos

    ctx = get_ctx(click_ctx)
    ctx.out.result(list_repos(base_url=ctx.settings.base_url, workspace=ctx.settings.workspace))


@app.command("connect")
def connect(
    click_ctx: typer.Context,
    repository: str = typer.Argument(
        ..., metavar="OWNER/REPO", help="Owner/name or GitHub clone URL."
    ),
    branch: str | None = typer.Option(
        None, help="Branch to scan; defaults to the connected or default branch."
    ),
    ai: bool | None = typer.Option(
        None,
        "--ai/--no-ai",
        help="Allow AI extraction. Off for new connections; preserved on reconnect.",
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for scan results."),
    wait_timeout: float = typer.Option(
        900.0,
        "--wait-timeout",
        help="Maximum wait in seconds; the remote scan continues on timeout.",
    ),
) -> None:
    """Connect a GitHub repo and start syncing its API collections. Requires --yes in CI."""
    from elva_cli.core.services.repo import connect_repo

    ctx = get_ctx(click_ctx)
    _emit(
        ctx,
        connect_repo(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            repository=repository,
            branch=branch,
            ai_enabled=ai,
            wait=wait,
            wait_timeout=wait_timeout,
            confirm=_confirmation(ctx),
            progress=lambda message: ctx.out.hint(printable(message)),
        ),
    )


@app.command("sync")
def sync(
    click_ctx: typer.Context,
    repository: str = typer.Argument(
        ...,
        metavar="REPO",
        help="Connected repository: owner/name, GitHub clone URL, or Elva repository ID.",
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for scan results."),
    wait_timeout: float = typer.Option(
        900.0,
        "--wait-timeout",
        help="Maximum wait in seconds; the remote scan continues on timeout.",
    ),
) -> None:
    """Scan the connected branch and reconcile API collections. Requires --yes in CI."""
    from elva_cli.core.services.repo import sync_repo

    ctx = get_ctx(click_ctx)
    _emit(
        ctx,
        sync_repo(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            repository=repository,
            wait=wait,
            wait_timeout=wait_timeout,
            confirm=_confirmation(ctx),
            progress=lambda message: ctx.out.hint(printable(message)),
        ),
    )


@app.command("status")
def status(
    click_ctx: typer.Context,
    job_id: str = typer.Argument(..., help="Scan job ID returned by connect or sync."),
    wait: bool = typer.Option(False, "--wait", help="Wait for this scan to finish."),
    wait_timeout: float = typer.Option(
        900.0,
        "--wait-timeout",
        help="Maximum wait in seconds; the remote scan continues on timeout.",
    ),
) -> None:
    """Inspect a scan, including progress, collection changes, warnings and commit SHA."""
    from elva_cli.core.services.repo import scan_status

    ctx = get_ctx(click_ctx)
    _emit(
        ctx,
        scan_status(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            job_id=job_id,
            wait=wait,
            wait_timeout=wait_timeout,
            progress=lambda message: ctx.out.hint(printable(message)),
        ),
    )


def _confirmation(ctx: Ctx) -> Callable[[str], None]:
    from elva_cli.ui.prompts import confirm

    def ask(name: str) -> None:
        if not confirm(
            None,
            ctx=ctx,
            prompt=(
                f"Sync {printable(name)}? This can update or remove generated collections "
                "and their MCP servers."
            ),
        ):
            raise typer.Exit(ExitCode.OK)

    return ask


def _emit(ctx: Ctx, result: RepoScanResult) -> None:
    ctx.out.result(result)
    if result.error:
        raise ElvaError(
            result.error.message,
            code=result.error.code,
            hint=result.error.hint,
            exit_code=ExitCode(result.error.exit_code),
        )
    if result.job is None and result.scan_job_id:
        ctx.out.hint(f"Inspect with 'elva repo status {result.scan_job_id}' in the same workspace.")
