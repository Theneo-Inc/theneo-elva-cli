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
    """Keeps `collection` a group for `list`, `show` and a future `endpoints`."""


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List the collections in the current workspace.

    Reads --workspace / ELVA_WORKSPACE; an account with a single workspace needs
    neither. Columns: ID, NAME, SPEC, ENDPOINTS, UPDATED. --json emits the raw
    array of collections instead.
    """
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
    """Show one collection in detail, by name or id.

    Reads --workspace / ELVA_WORKSPACE like `list`. When a name matches more than
    one collection, an interactive shell offers a picker; otherwise it stops and
    lists the candidates so you can pass an id. --json emits the collection with
    its MCP servers nested inside.
    """
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


def _workspace(ctx: Ctx) -> tuple[str, str, str]:
    """(base_url, token, company_id) for the resolved workspace.

    Resolution lives here, in the command layer, so the services below take
    plain values. resolve_workspace (ELVA-156) is shared with the other
    commands; its messages are left as they are, except that a
    workspace-selection failure reached from here should also point at
    ELVA_WORKSPACE, the env form of the flag its hint already names.
    """
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
    """Let the user choose among same-named collections; returns the chosen id.

    Only reached on an interactive shell (`show` re-raises otherwise), so the
    reused prompt helper never has to refuse. Candidates are labelled by id and
    updated date, the two things that tell them apart when the name cannot.
    """
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
