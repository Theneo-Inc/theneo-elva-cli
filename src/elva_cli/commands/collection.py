from __future__ import annotations

import typer

from elva_cli.context import get_ctx

app = typer.Typer(
    name="collection",
    help="Inspect the collections in a workspace.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keeps `collection` a group for future `show` and `endpoints` commands."""


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List the collections in the current workspace.

    Reads --workspace / ELVA_WORKSPACE; an account with a single workspace needs
    neither. Columns: ID, NAME, SPEC, ENDPOINTS, UPDATED. --json emits the raw
    array of collections instead.
    """
    from elva_cli.core.collections import CollectionSummaries, list_collections

    ctx = get_ctx(click_ctx)
    summaries = list_collections(ctx)
    ctx.out.result(CollectionSummaries(summaries))
