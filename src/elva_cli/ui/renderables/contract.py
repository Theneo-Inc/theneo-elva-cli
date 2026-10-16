from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from elva_cli.core.services.contract_result import (  # noqa: TC001
    ContractList,
    ContractPublished,
    ContractResult,
)
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render


@render.register
def _(result: ContractList) -> RenderableType:
    if not result.contracts:
        return Text("No API contracts in this workspace.")
    table = Table(box=None, pad_edge=False)
    for name in ("ID", "NAME", "STATUS", "VERSION", "SOURCE DRIFT"):
        table.add_column(name)
    for row in result.contracts:
        table.add_row(
            *(printable(str(row.get(key, "-"))) for key in ("id", "name", "status", "version")),
            "yes" if row.get("drifted") else "no",
        )
    return table


@render.register
def _(result: ContractResult) -> RenderableType:
    row = result.contract
    lines = [Text(printable(f"{result.action.capitalize()}: {row['name']} ({row['id']})"))]
    for key in ("status", "version", "audience", "description", "drifted", "hasUnpublishedChanges"):
        if key in row:
            lines.append(Text(printable(f"{key}: {row[key]}")))
    if isinstance(row.get("collections"), list):
        lines.append(Text(f"Source collections: {len(row['collections'])}"))
    governance = row.get("governance")
    if isinstance(governance, dict) and governance.get("requireApproval"):
        approval = governance.get("approval") or {}
        state = approval.get("status", "pending") if isinstance(approval, dict) else "pending"
        lines.append(Text(printable(f"Approval: {state}")))
    return Group(*lines)


@render.register
def _(result: ContractPublished) -> RenderableType:
    title = Text("Contract published." if result.complete else "Contract publication incomplete.")
    table = Table(box=None, pad_edge=False)
    for name in ("DESTINATION", "STATUS", "DETAIL"):
        table.add_column(name)
    for row in result.results:
        table.add_row(
            *(printable(str(row.get(key, ""))) for key in ("platform", "status", "detail"))
        )
    return Group(title, table)
