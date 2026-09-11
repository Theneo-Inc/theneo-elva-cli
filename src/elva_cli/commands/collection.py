from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx

if TYPE_CHECKING:
    from elva_cli.context import Ctx
    from elva_cli.core.collections import CollectionSummary
    from elva_cli.errors import UsageError

app = typer.Typer(
    name="collection",
    help="Inspect the collections in a workspace.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keeps `collection` a group for `list`, `show` and `endpoints`."""


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List the collections in the current workspace."""
    from elva_cli.core.collections import CollectionSummaries, list_collections

    ctx = get_ctx(click_ctx)
    base_url, token, company_id = _workspace(ctx)
    summaries = list_collections(base_url, token, company_id)
    ctx.out.result(CollectionSummaries(summaries))


@app.command("show")
def show(
    click_ctx: typer.Context,
    collection: str = typer.Argument(
        ..., metavar="COLLECTION", help="The collection to show, by name or id."
    ),
) -> None:
    """Show one collection, by name or id."""
    from elva_cli.core.collections import AmbiguousCollection, get_collection

    ctx = get_ctx(click_ctx)
    base_url, token, company_id = _workspace(ctx)

    try:
        detail = get_collection(base_url, token, company_id, collection)
    except AmbiguousCollection as exc:
        if not ctx.interactive:
            raise
        chosen = _pick(exc.candidates, ctx)
        detail = get_collection(base_url, token, company_id, chosen)

    ctx.out.result(detail)
    if not detail.mcps and not ctx.out.json_mode:
        ctx.out.hint("No MCP servers.")


@app.command("endpoints")
def endpoints(
    click_ctx: typer.Context,
    collection: str = typer.Argument(
        ..., metavar="COLLECTION", help="The collection whose spec to read, by name or id."
    ),
    tags: list[str] = typer.Option(
        [], "--tag", metavar="TAG", help="Keep only operations with this tag. Repeatable."
    ),
    methods: list[str] = typer.Option(
        [], "--method", metavar="METHOD", help="Keep only this HTTP method. Repeatable."
    ),
    path_prefixes: list[str] = typer.Option(
        [], "--path", metavar="PREFIX", help="Keep only paths starting with this. Repeatable."
    ),
) -> None:
    """List the operations in a collection's uploaded OpenAPI spec."""
    from elva_cli.core.collections import (
        AmbiguousCollection,
        get_collection_operations,
        resolve_collection,
    )
    from elva_cli.core.openapi_ops import CollectionOperations, filter_operations

    ctx = get_ctx(click_ctx)
    base_url, token, company_id = _workspace(ctx)

    # Resolved here too so the picker stays in the command layer and the count
    # below has something to compare against.
    try:
        summary = resolve_collection(base_url, token, company_id, collection)
    except AmbiguousCollection as exc:
        if not ctx.interactive:
            raise
        chosen = _pick(exc.candidates, ctx)
        summary = resolve_collection(base_url, token, company_id, chosen)

    operations = get_collection_operations(base_url, token, company_id, summary.id)

    # The listing keeps its own count. If it disagrees with the spec, say so but
    # carry on: the spec is what everything downstream uses.
    if summary.endpoint_count is not None and summary.endpoint_count != len(operations):
        ctx.out.warn(
            f"the workspace lists {summary.endpoint_count} endpoints "
            f"but the spec has {len(operations)}"
        )

    selected = filter_operations(
        operations,
        tags=tuple(tags),
        methods=tuple(methods),
        path_prefixes=tuple(path_prefixes),
    )
    ctx.out.result(CollectionOperations(selected))
    if not selected and not ctx.out.json_mode:
        filtered = bool(tags or methods or path_prefixes)
        ctx.out.hint(
            "No operations match those filters." if filtered else "This spec has no operations."
        )


def _workspace(ctx: Ctx) -> tuple[str, str, str]:
    """(base_url, token, company_id) for the resolved workspace."""
    from elva_cli.auth import get_access_token
    from elva_cli.core.api.targets import resolve_workspace
    from elva_cli.errors import UsageError

    base_url = ctx.settings.base_url
    token = get_access_token(base_url=base_url)
    try:
        target = resolve_workspace(base_url=base_url, token=token, workspace=ctx.settings.workspace)
    except UsageError as exc:
        raise _also_name_the_env(exc) from exc
    return base_url, token, target.id


def _also_name_the_env(exc: UsageError) -> UsageError:
    from elva_cli.errors import UsageError

    hint = exc.hint
    if hint and "--workspace" in hint and "ELVA_WORKSPACE" not in hint:
        hint = f"{hint} You can also set ELVA_WORKSPACE."
    return UsageError(str(exc), hint=hint)


def _pick(candidates: tuple[CollectionSummary, ...], ctx: Ctx) -> str:
    """Ask which of the same-named collections was meant. Returns its id."""
    from elva_cli.ui import prompts

    labels = {_label(candidate): candidate for candidate in candidates}
    chosen = prompts.select(
        None,
        prompt=f"More than one collection is named {candidates[0].name!r}. Which one?",
        choices=list(labels),
        flag="--collection",
        ctx=ctx,
    )
    return labels[chosen].id


def _label(candidate: CollectionSummary) -> str:
    updated = candidate.updated_at[:10] if candidate.updated_at else "unknown"
    return f"{candidate.id}  (updated {updated})"
