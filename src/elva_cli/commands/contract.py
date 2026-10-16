"""Contract lifecycle commands, using JSON for full contract definitions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import ApiError, UsageError
from elva_cli.safe_text import printable

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from elva_cli.context import Ctx

app = typer.Typer(
    name="contract", help="Manage API contracts and their releases.", no_args_is_help=True
)


@app.command("list")
def list_(click_ctx: typer.Context) -> None:
    """List API contracts in the active workspace."""
    from elva_cli.core.services.contract import list_contracts

    ctx = get_ctx(click_ctx)
    ctx.out.result(list_contracts(base_url=ctx.settings.base_url, workspace=ctx.settings.workspace))


@app.command("show")
def show(click_ctx: typer.Context, contract: str) -> None:
    """Inspect a contract by exact name or ID. Use global --json for all fields."""
    from elva_cli.core.services.contract import show_contract

    ctx = get_ctx(click_ctx)
    ctx.out.result(
        show_contract(
            base_url=ctx.settings.base_url, workspace=ctx.settings.workspace, reference=contract
        )
    )


@app.command("create")
def create(
    click_ctx: typer.Context,
    name: str | None = typer.Option(None, help="Name of a new draft contract."),
    prompt: str | None = typer.Option(None, help="Use Elva AI to select endpoints and fields."),
    source: list[str] = typer.Option(
        [], help="Source collection ID; repeat to narrow the catalog."
    ),
    plan: bool = typer.Option(False, help="Review an AI plan without applying it."),
    out: Path | None = typer.Option(None, help="Save the AI plan to a new JSON file."),
    audience: str | None = typer.Option(None, help="partner, internal, public, or ai_agent."),
    from_file: str | None = typer.Option(
        None, "--from", help="Full contract JSON file, or '-' for stdin."
    ),
) -> None:
    """Create a draft from a name or JSON definition. Requires --yes in CI."""
    from elva_cli.core.services.contract import create_contract

    if prompt is not None:
        if from_file is not None:
            raise UsageError("Use --prompt or --from, not both.")
        _ai(click_ctx, prompt, source, plan, out, None, name, audience, "compose")
        return
    if source or plan or out:
        raise UsageError("--source, --plan and --out require --prompt.")
    if from_file is not None and (name is not None or audience is not None):
        raise UsageError("Use --from or --name/--audience, not both.")
    if audience is not None and audience not in {"partner", "internal", "public", "ai_agent"}:
        raise UsageError("Audience must be partner, internal, public, or ai_agent.")
    body = _body(from_file) if from_file is not None else {"name": name}
    if audience is not None:
        body["audience"] = audience
    ctx = get_ctx(click_ctx)
    ctx.out.result(
        create_contract(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            body=body,
            confirm=_confirm(ctx),
        )
    )


@app.command("update")
def update(
    click_ctx: typer.Context,
    contract: str,
    from_file: str | None = typer.Option(
        None, "--from", help="JSON fields to save, or '-' for stdin."
    ),
    prompt: str | None = typer.Option(None, help="Ask Elva AI to change this contract."),
    source: list[str] = typer.Option(
        [], help="Source collection ID; repeat to narrow the catalog."
    ),
    plan: bool = typer.Option(False, help="Review the AI plan without applying it."),
    out: Path | None = typer.Option(None, help="Save the AI plan to a new JSON file."),
    mode: str = typer.Option("schema", help="schema for fields; compose for endpoint selection."),
) -> None:
    """Save contract changes without publishing. Requires --yes in CI."""
    if prompt is not None:
        if from_file is not None:
            raise UsageError("Use --prompt or --from, not both.")
        _ai(click_ctx, prompt, source, plan, out, contract, None, None, mode)
        return
    if from_file is None or source or plan or out or mode != "schema":
        raise UsageError("Use --from JSON or --prompt with AI planning options.")
    _change(click_ctx, contract, "update", _body(from_file))


@app.command("sync")
def sync(
    click_ctx: typer.Context,
    contract: str,
    from_file: str = typer.Option(
        ...,
        "--from",
        help="Reviewed sync JSON: changes, collections, optional field snapshots. '-' reads stdin.",
    ),
) -> None:
    """Apply reviewed source changes to a contract without publishing. Requires --yes in CI."""
    _change(click_ctx, contract, "sync", _body(from_file))


@app.command("approve")
def approve(
    click_ctx: typer.Context,
    contract: str,
    note: str | None = typer.Option(None, help="Decision note (up to 500 characters)."),
) -> None:
    """Approve current content as an assigned approver. Requires --yes in CI."""
    _change(click_ctx, contract, "approve", _note(note))


@app.command("reject")
def reject(
    click_ctx: typer.Context,
    contract: str,
    note: str | None = typer.Option(None, help="Decision note (up to 500 characters)."),
) -> None:
    """Reject current content as an assigned approver. Requires --yes in CI."""
    _change(click_ctx, contract, "reject", _note(note))


@app.command("publish")
def publish(
    click_ctx: typer.Context,
    contract: str,
    acknowledge_breaking_changes: bool = typer.Option(
        False, help="Acknowledge warnings required by the release policy."
    ),
) -> None:
    """Publish saved content to its configured destinations. Requires --yes in CI."""
    _change(
        click_ctx,
        contract,
        "publish",
        {"acknowledgeBreakingChanges": True} if acknowledge_breaking_changes else {},
    )


@app.command("delete")
def delete(click_ctx: typer.Context, contract: str) -> None:
    """Delete a contract and its associated artifacts/deployment. Requires --yes in CI."""
    _change(click_ctx, contract, "delete", {})


def _note(note: str | None) -> dict[str, Any]:
    if note is not None and len(note) > 500:
        raise UsageError("Decision notes must be at most 500 characters.")
    return {"note": note} if note is not None else {}


def _body(source: str) -> dict[str, Any]:
    from elva_cli.core.services.contract import MAX_BYTES, read_body
    from elva_cli.ui.input import read_stdin

    return read_body(
        None if source == "-" else Path(source),
        read_stdin(max_bytes=MAX_BYTES) if source == "-" else None,
    )


def _confirm(ctx: Ctx) -> Callable[[str], None]:
    from elva_cli.ui.prompts import confirm

    def ask(message: str) -> None:
        if not confirm(None, prompt=printable(message), ctx=ctx):
            raise typer.Exit(0)

    return ask


def _change(click_ctx: typer.Context, reference: str, action: str, body: dict[str, Any]) -> None:
    from elva_cli.core.services.contract import change_contract
    from elva_cli.core.services.contract_result import ContractPublished

    ctx = get_ctx(click_ctx)
    result = change_contract(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        reference=reference,
        action=action,
        body=body,
        confirm=_confirm(ctx),
    )
    ctx.out.result(result)
    if isinstance(result, ContractPublished) and not result.complete:
        raise ApiError(
            "Contract publication was incomplete.",
            code="ELVA_CONTRACT_PUBLISH_INCOMPLETE",
            hint="Review each destination result. Some destinations may already be published.",
        )


def _ai(
    click_ctx: typer.Context,
    prompt: str,
    source: list[str],
    plan: bool,
    out: Path | None,
    reference: str | None,
    name: str | None,
    audience: str | None,
    mode: str,
) -> None:
    from elva_cli.core.services.plan import apply_plan, create_plan, save_plan

    if mode not in {"compose", "schema"}:
        raise UsageError("AI mode must be compose or schema.")
    ctx = get_ctx(click_ctx)
    body: dict[str, Any] = {"prompt": prompt, "mode": mode}
    for key, value in (("collectionIds", source), ("name", name), ("audience", audience)):
        if value:
            body[key] = value
    result = create_plan(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        body=body,
        reference=reference,
        progress=ctx.out.hint,
    )
    save_plan(result, out)
    if plan or out:
        ctx.out.result(result)
        return
    # A human can review the same payload an agent receives before confirming.
    import json

    ctx.out.hint(printable(json.dumps(result.plan["review"], indent=2, ensure_ascii=False)))
    ctx.out.result(
        apply_plan(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            plan=result.plan,
            confirm=_confirm(ctx),
        )
    )
