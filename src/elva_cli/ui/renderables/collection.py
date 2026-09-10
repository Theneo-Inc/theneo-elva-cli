from __future__ import annotations

# Imported at runtime, not under TYPE_CHECKING: singledispatch resolves this
# function's annotations when register() runs, so every name in them -- the
# dispatch type and the return type alike -- has to actually exist.
from rich.console import RenderableType  # noqa: TC002
from rich.table import Table
from rich.text import Text

from elva_cli.core.collections import CollectionSummaries  # noqa: TC001
from elva_cli.ui.renderables.base import render


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


def _date(value: str | None) -> str:
    """Just the calendar day; the API sends a full ISO 8601 timestamp."""
    if not value:
        return "-"
    return value[:10]
