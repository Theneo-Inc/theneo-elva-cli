from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from elva_cli.core.services.insights_result import InsightChecks, InsightReview  # noqa: TC001
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render


@render.register
def _(result: InsightChecks) -> RenderableType:
    table = Table(box=None, pad_edge=False)
    for name in ("ID", "CATEGORY", "CHECK", "SEVERITY"):
        table.add_column(name)
    for row in result.checks:
        table.add_row(
            *(printable(str(row.get(key, ""))) for key in ("id", "category", "name", "severity"))
        )
    return table if result.checks else Text("No matching insight checks.")


@render.register
def _(result: InsightReview) -> RenderableType:
    review = result.review
    score = (
        f"{review['overallScore']:g}/100 ({review.get('overallGrade', '')})"
        if review["scorable"]
        else f"N/A — {review.get('unscorableReason', 'not scorable')}"
    )
    lines: list[RenderableType] = [Text(printable(f"{result.source}: {score}"))]
    lines.append(Text(printable(f"Operations: {review.get('operationCount', '?')}")))
    for category, value in review["scores"].items():
        lines.append(
            Text(
                printable(
                    f"{category}: {value.get('percentage', '?')} ({value.get('grade', 'N/A')})"
                )
            )
        )
    table = Table(box=None, pad_edge=False)
    for name in ("CHECK", "STATUS", "DETAIL"):
        table.add_column(name)
    for check in review["checks"]:
        table.add_row(*(printable(str(check.get(key, ""))) for key in ("id", "status", "comments")))
    return Group(*lines, Text(""), table)
