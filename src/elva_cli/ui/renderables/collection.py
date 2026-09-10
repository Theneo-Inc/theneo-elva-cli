from __future__ import annotations

# Imported at runtime, not under TYPE_CHECKING: singledispatch resolves this
# function's annotations when register() runs, so every name in them -- the
# dispatch type and the return type alike -- has to actually exist.
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from elva_cli.core.collections import CollectionDetail, CollectionSummaries  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render


@render.register
def _(result: CollectionSummaries) -> RenderableType:
    if not result:
        return Text("No collections in this workspace.", style="elva.dim")

    table = Table(box=None, pad_edge=False, header_style="elva.key")
    table.add_column("ID")
    table.add_column("NAME")
    table.add_column("SPEC")
    table.add_column("ENDPOINTS", justify="right")
    table.add_column("UPDATED")
    for summary in result:
        table.add_row(
            summary.id,
            summary.name,
            "yes" if summary.spec_uploaded else "no",
            "-" if summary.endpoint_count is None else str(summary.endpoint_count),
            _date(summary.updated_at),
        )
    return table


@render.register
def _(result: CollectionDetail) -> RenderableType:
    headline = Text(result.name, style="elva.ok")
    body: list[RenderableType] = [headline, Text(""), aligned_rows(_detail_rows(result))]

    if result.mcps:
        body += [Text(""), _mcp_table(result)]
    return Group(*body)


def _detail_rows(result: CollectionDetail) -> list[tuple[str, Text, Text]]:
    rows: list[tuple[str, Text, Text]] = [
        ("id", Text(result.id, style="elva.dim"), Text("")),
        ("spec", _spec(result), Text("")),
        ("endpoints", Text(str(result.endpoint_count)), Text("")),
    ]
    if result.labels:
        rows.append(("labels", Text(", ".join(result.labels)), Text("")))
    if result.source:
        rows.append(("source", Text(result.source), Text("")))
    rows.append(("updated", Text(_date(result.updated_at)), Text("")))
    return rows


def _spec(result: CollectionDetail) -> Text:
    """Whether a spec is uploaded, and its title and version when there is one.

    A collection with no spec is shown as such -- it is a normal state, not a
    fault."""
    if not result.spec_uploaded:
        return Text("no")
    detail = result.spec_title or "(untitled)"
    if result.spec_version:
        detail = f"{detail} ({result.spec_version})"
    return Text(f"yes — {detail}")


def _mcp_table(result: CollectionDetail) -> Table:
    table = Table(box=None, pad_edge=False, header_style="elva.key", title="MCP SERVERS")
    table.title_justify = "left"
    table.add_column("NAME")
    table.add_column("SLUG")
    table.add_column("STATUS")
    table.add_column("TOOLS", justify="right")
    for mcp in result.mcps:
        table.add_row(
            mcp.name,
            mcp.slug or "-",
            mcp.status,
            "-" if mcp.tool_count is None else str(mcp.tool_count),
        )
    return table


def _date(value: str | None) -> str:
    """Just the calendar day; the API sends a full ISO 8601 timestamp."""
    if not value:
        return "-"
    return value[:10]
